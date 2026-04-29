"""Daily drift sync: reconcile dashboard state with VCD reality.

For each deployment:

1. Skip if an Operation is in-flight (PENDING/RUNNING).
2. Acquire a short-TTL Redis lock keyed by the deployment's org.
3. Materialise a temp workspace from the latest version's HCL + provider.tf.
4. ``terraform init`` then ``terraform plan -refresh-only -detailed-exitcode``.
5. Parse drift:
   - mods → ``needs_review``
   - deletions → ``needs_review``
   - addition-count hints (VCD enum vs state list) → ``needs_review`` if any type has more VCD objects than state objects
6. Write ``drift_reports`` row; never auto-apply; never auto-import (see PHASE-04).
"""

from __future__ import annotations

import logging
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.aria_attribution import Attribution, retag_hcl, DRIFT_SYNC_USER
from app.core import minio_client, version_store
from app.core.locking import acquire_org_lock, get_org_lock_holder, release_org_lock
from app.core.plan_parser import parse_show_json
from app.core.drift_importer import import_unmanaged
from app.core.state_to_hcl import patch_hcl_from_state, remove_resource_blocks
from app.core.tf_runner import TerraformRunner
from app.database import async_session
from app.models.deployment import Deployment
from app.models.deployment_version import DeploymentVersion
from app.models.drift_report import DriftReport
from app.models.operation import Operation, OperationStatus

logger = logging.getLogger(__name__)

_IN_FLIGHT = (OperationStatus.PENDING, OperationStatus.RUNNING)


# Pattern to extract resource address from terraform error context.
# Example line: ``  with vcd_nsxt_edgegateway_static_route.route_2,``
_ENF_WITH_RE = re.compile(r'^\s*with\s+(\S+\.\S+?),\s*$', re.MULTILINE)

# Markers signalling an ENF (entity-not-found) error in VCD provider output.
_ENF_MARKERS = (
    "entity not found",
    "does not exist",
    "FORBIDDEN - [",  # VCD returns FORBIDDEN with ENF detail on some reads
)


def _extract_enf_addresses(stdout: str, stderr: str) -> list[str]:
    """Scan terraform plan output for ENF errors. Return list of resource addresses.

    Addresses are deduplicated preserving first-seen order. Only addresses
    within error blocks that mention an ENF marker are collected.
    """
    combined = f"{stdout}\n{stderr}"
    # Split on "Error:" to process each error block independently.
    chunks = combined.split("\nError:")
    enf_addrs: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        low = chunk.lower()
        if not any(m.lower() in low for m in _ENF_MARKERS):
            continue
        for m in _ENF_WITH_RE.finditer(chunk):
            addr = m.group(1).strip()
            if addr not in seen:
                seen.add(addr)
                enf_addrs.append(addr)
    return enf_addrs


async def _state_rm(runner: TerraformRunner, addresses: list[str]) -> tuple[bool, str]:
    """Run ``terraform state rm`` for each address. Returns (all_succeeded, log)."""
    log_lines: list[str] = []
    all_ok = True
    for addr in addresses:
        r = await runner._exec(
            "state", "rm", "-no-color", addr, emit_exit=False,
        )
        log_lines.append(f"state rm {addr}: rc={r.return_code}")
        if r.return_code != 0:
            log_lines.append(f"  stderr: {r.stderr[:300]}")
            all_ok = False
    return all_ok, "\n".join(log_lines)


async def _latest_version(db: AsyncSession, deployment_id: uuid.UUID) -> DeploymentVersion | None:
    result = await db.execute(
        select(DeploymentVersion)
        .where(DeploymentVersion.deployment_id == deployment_id)
        .order_by(DeploymentVersion.version_num.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _has_in_flight_op(db: AsyncSession, deployment_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(Operation.id)
        .where(Operation.deployment_id == deployment_id)
        .where(Operation.status.in_(_IN_FLIGHT))
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


def _render_provider_tf(deployment_id: uuid.UUID) -> str:
    # Lazy import to avoid circular import at module load.
    from app.api.routes.migration import _render_provider_tf as r
    return r(deployment_id)


async def _prepare_workspace(
    deployment: Deployment, version: DeploymentVersion, work_dir: Path,
    *, op_id: str | None = None,
) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    hcl = await minio_client.get_text(version.hcl_key)
    # Phase 8: retag descriptions so any apply (auto-imported drift,
    # patched HCL) emits VCD events attributed to drift-sync-cron rather
    # than the original creator.
    attribution = Attribution(
        kc_username=DRIFT_SYNC_USER,
        op_id=op_id or f"deployment-{deployment.id}",
    )
    (work_dir / "main.tf").write_text(retag_hcl(hcl, attribution), encoding="utf-8")
    (work_dir / "provider.tf").write_text(
        _render_provider_tf(deployment.id), encoding="utf-8"
    )


async def _addition_count_hints(
    work_dir: Path, deployment: Deployment, runner: TerraformRunner
) -> list[dict]:
    """Compare counts: VCD enum vs ``terraform state list`` per resource type.

    Positive delta → likely addition in VCD. We don't auto-import; we just
    surface the delta so the admin can investigate. Negative delta is
    harmless noise here (deletions are caught by refresh-only).
    """
    from app.core import tf_import

    edge = deployment.target_edge_id
    org = deployment.target_org

    try:
        ip_sets = await tf_import._list_ip_sets(edge)
    except Exception:
        ip_sets = []
    try:
        app_profiles = await tf_import._list_app_port_profiles(org)
    except Exception:
        app_profiles = []
    try:
        static_routes = await tf_import._list_static_routes(edge)
    except Exception:
        static_routes = []
    try:
        nat_rules = await tf_import._list_nat_rules(edge)
    except Exception:
        nat_rules = []

    state_result = await runner.state_list()
    state_addresses = state_result.stdout.strip().splitlines() if state_result.success else []

    def _count_prefix(prefix: str) -> int:
        return sum(1 for a in state_addresses if a.startswith(prefix))

    pairs = [
        ("vcd_nsxt_ip_set", ip_sets),
        ("vcd_nsxt_app_port_profile", app_profiles),
        ("vcd_nsxt_edgegateway_static_route", static_routes),
        ("vcd_nsxt_nat_rule", nat_rules),
    ]

    hints: list[dict] = []
    for tf_type, vcd_list in pairs:
        vcd_n = len(vcd_list)
        state_n = _count_prefix(tf_type)
        delta = vcd_n - state_n
        if delta > 0:
            hints.append({
                "type": tf_type,
                "vcd_count": vcd_n,
                "state_count": state_n,
                "delta": delta,
            })
    return hints


async def _write_report(
    db: AsyncSession,
    deployment_id: uuid.UUID,
    *,
    has_changes: bool | None,
    additions: list,
    modifications: list,
    deletions: list,
    auto_resolved: bool,
    resolution: str | None,
    error: str | None,
    version_id: uuid.UUID | None = None,
) -> DriftReport:
    row = DriftReport(
        id=uuid.uuid4(),
        deployment_id=deployment_id,
        has_changes=has_changes,
        additions=additions,
        modifications=modifications,
        deletions=deletions,
        auto_resolved=auto_resolved,
        resolution=resolution,
        error=error,
        version_id=version_id,
    )
    db.add(row)
    return row


async def sync_deployment(deployment_id: uuid.UUID, *, triggered_by: str = "cron") -> uuid.UUID:
    """Run drift sync for a single deployment. Returns drift_report.id.

    Never raises for per-deployment errors — records them in the report.
    """
    op_id = uuid.uuid4()
    workspace = Path(settings.tf_workspace_base) / "drift" / f"{deployment_id}-{op_id}"

    async with async_session() as db:
        deployment = await db.get(Deployment, deployment_id)
        if deployment is None:
            logger.warning("drift_sync: deployment %s not found", deployment_id)
            return op_id

        # In-flight guard
        if await _has_in_flight_op(db, deployment_id):
            logger.info("drift_sync: deployment %s has in-flight op, skipping", deployment_id)
            report = await _write_report(
                db, deployment_id,
                has_changes=None, additions=[], modifications=[], deletions=[],
                auto_resolved=False, resolution="skipped_locked",
                error="Deployment has in-flight operation",
            )
            deployment.last_drift_check = datetime.now(timezone.utc)
            await db.commit()
            return report.id

        # Redis lock check (other orchestrator holds it)
        holder = await get_org_lock_holder(deployment.target_org)
        if holder:
            logger.info(
                "drift_sync: org %s locked by %s, skipping %s",
                deployment.target_org, holder, deployment_id,
            )
            report = await _write_report(
                db, deployment_id,
                has_changes=None, additions=[], modifications=[], deletions=[],
                auto_resolved=False, resolution="skipped_locked",
                error=f"Org lock held by {holder}",
            )
            deployment.last_drift_check = datetime.now(timezone.utc)
            await db.commit()
            return report.id

        acquired = await acquire_org_lock(
            deployment.target_org, str(op_id), ttl=settings.drift_sync_lock_ttl,
        )
        if not acquired:
            logger.info("drift_sync: could not acquire lock for %s", deployment.target_org)
            report = await _write_report(
                db, deployment_id,
                has_changes=None, additions=[], modifications=[], deletions=[],
                auto_resolved=False, resolution="skipped_locked",
                error="Failed to acquire org lock (race)",
            )
            deployment.last_drift_check = datetime.now(timezone.utc)
            await db.commit()
            return report.id

        try:
            version = await _latest_version(db, deployment_id)
            if version is None:
                report = await _write_report(
                    db, deployment_id,
                    has_changes=None, additions=[], modifications=[], deletions=[],
                    auto_resolved=False, resolution="errored",
                    error="No versions exist for deployment",
                )
                deployment.last_drift_check = datetime.now(timezone.utc)
                await db.commit()
                return report.id

            try:
                await _prepare_workspace(deployment, version, workspace)
            except Exception as exc:
                logger.exception("drift_sync: workspace prep failed for %s", deployment_id)
                report = await _write_report(
                    db, deployment_id,
                    has_changes=None, additions=[], modifications=[], deletions=[],
                    auto_resolved=False, resolution="errored",
                    error=f"Workspace prep failed: {exc}",
                )
                deployment.last_drift_check = datetime.now(timezone.utc)
                await db.commit()
                return report.id

            runner = TerraformRunner(workspace)

            init_result = await runner.init()
            if not init_result.success:
                report = await _write_report(
                    db, deployment_id,
                    has_changes=None, additions=[], modifications=[], deletions=[],
                    auto_resolved=False, resolution="errored",
                    error=f"terraform init failed: {init_result.stderr[:1000]}",
                )
                deployment.last_drift_check = datetime.now(timezone.utc)
                await db.commit()
                return report.id

            plan_result = await runner.plan_refresh_only()
            enf_removed: list[str] = []
            if plan_result.return_code == 1:
                # ENF recovery: if plan failed because VCD provider couldn't
                # read resources deleted externally, surgically drop them
                # from state and retry. Caught in drift_report.deletions.
                combined_err = f"{plan_result.stdout}\n{plan_result.stderr}"
                enf_addrs = _extract_enf_addresses(
                    plan_result.stdout, plan_result.stderr,
                )
                if enf_addrs:
                    logger.info(
                        "drift_sync: ENF detected for %s: %s",
                        deployment_id, enf_addrs,
                    )
                    ok, rm_log = await _state_rm(runner, enf_addrs)
                    if not ok:
                        report = await _write_report(
                            db, deployment_id,
                            has_changes=None, additions=[], modifications=[], deletions=[],
                            auto_resolved=False, resolution="errored",
                            error=(
                                "ENF recovery failed while running `state rm`:\n"
                                + rm_log[:1500]
                            ),
                        )
                        deployment.last_drift_check = datetime.now(timezone.utc)
                        await db.commit()
                        return report.id
                    enf_removed = enf_addrs
                    plan_result = await runner.plan_refresh_only()
                if plan_result.return_code == 1:
                    report = await _write_report(
                        db, deployment_id,
                        has_changes=None, additions=[], modifications=[], deletions=[],
                        auto_resolved=False, resolution="errored",
                        error=(
                            "plan -refresh-only failed (after ENF retry)"
                            if enf_removed else
                            "plan -refresh-only failed"
                        ) + f": {combined_err[:1000]}",
                    )
                    deployment.last_drift_check = datetime.now(timezone.utc)
                    await db.commit()
                    return report.id

            modifications: list = []
            deletions: list = []
            # ENF-removed resources are effective deletions. Surface them in
            # the report and remove their HCL blocks so the snapshot reflects
            # new reality. Happens before plan rc==2 parse so both sources
            # merge into the deletions list.
            if enf_removed:
                for addr in enf_removed:
                    rtype, _, rname = addr.partition(".")
                    deletions.append({
                        "address": addr,
                        "type": rtype,
                        "name": rname,
                        "reason": "entity_not_found_in_vcd",
                    })
                try:
                    main_tf_path = workspace / "main.tf"
                    cur_hcl = main_tf_path.read_text(encoding="utf-8")
                    new_hcl, removed_blocks = remove_resource_blocks(
                        cur_hcl, enf_removed,
                    )
                    if removed_blocks:
                        main_tf_path.write_text(new_hcl, encoding="utf-8")
                        logger.info(
                            "drift_sync: removed HCL blocks for ENF resources %s",
                            removed_blocks,
                        )
                except Exception:
                    logger.exception(
                        "drift_sync: HCL block removal failed for %s", deployment_id,
                    )
            if plan_result.return_code == 2:
                show_result = await runner.show_plan_json()
                if not show_result.success:
                    report = await _write_report(
                        db, deployment_id,
                        has_changes=None, additions=[], modifications=[], deletions=[],
                        auto_resolved=False, resolution="errored",
                        error=f"terraform show failed: {show_result.stderr[:1000]}",
                    )
                    deployment.last_drift_check = datetime.now(timezone.utc)
                    await db.commit()
                    return report.id
                try:
                    parsed = parse_show_json(show_result.stdout)
                    modifications = [m.as_json() for m in parsed.modifications]
                    deletions = [d.as_json() for d in parsed.deletions]
                except Exception as exc:
                    logger.exception("drift_sync: parse failed for %s", deployment_id)
                    report = await _write_report(
                        db, deployment_id,
                        has_changes=None, additions=[], modifications=[], deletions=[],
                        auto_resolved=False, resolution="errored",
                        error=f"plan parse failed: {exc}",
                    )
                    deployment.last_drift_check = datetime.now(timezone.utc)
                    await db.commit()
                    return report.id

            # Persist refreshed state to backend so subsequent import_unmanaged
            # and HCL patcher see post-drift truth. Needed when TF detected
            # drift (rc==2) or we surgically state-rm'd ENF resources.
            import json as _json

            if plan_result.return_code == 2 or enf_removed:
                apply_result = await runner.apply()
                if not apply_result.success:
                    logger.warning(
                        "drift_sync: refresh-only apply failed for %s: %s",
                        deployment_id, apply_result.stderr[:500],
                    )

            # Regenerate HCL from refreshed state so drift snapshot
            # records real post-drift values, not stale pre-drift ones.
            # Enables meaningful rollback to either pre- or post-drift version.
            if plan_result.return_code == 2:
                try:
                    prev_state_bytes = await minio_client.get_bytes(
                        version.state_key,
                    )
                    prev_state = _json.loads(prev_state_bytes or b"{}")
                    show_new = await runner._exec(
                        "show", "-no-color", "-json", emit_exit=False,
                    )
                    if show_new.success and show_new.stdout.strip():
                        new_state = _json.loads(show_new.stdout)
                        prev_hcl = (workspace / "main.tf").read_text(
                            encoding="utf-8"
                        )
                        patched, summary = patch_hcl_from_state(
                            prev_hcl, prev_state, new_state,
                        )
                        if summary.get("patched", 0) > 0:
                            (workspace / "main.tf").write_text(
                                patched, encoding="utf-8",
                            )
                            logger.info(
                                "drift_sync: HCL patched for %s (resources=%d, skipped=%s)",
                                deployment_id,
                                summary["patched"],
                                summary.get("skipped"),
                            )
                except Exception:
                    logger.exception(
                        "drift_sync: HCL state→HCL patch failed for %s (continuing with unpatched HCL)",
                        deployment_id,
                    )

            # Auto-import unmanaged VCD resources (admin-created directly in
            # VCD). This is the "captures additions" half of full-cycle drift
            # sync. Import mutates state + appends HCL blocks in-place.
            additions: list = []
            skipped_imports: list = []
            try:
                show_cur = await runner._exec(
                    "show", "-no-color", "-json", emit_exit=False,
                )
                cur_state = (
                    _json.loads(show_cur.stdout)
                    if show_cur.success and show_cur.stdout.strip()
                    else {"resources": []}
                )
                import_summary = await import_unmanaged(
                    runner, workspace,
                    target_org=deployment.target_org,
                    target_vdc=deployment.target_vdc,
                    target_vdc_id=deployment.target_vdc_id,
                    target_edge_id=deployment.target_edge_id,
                    target_edge_name=deployment.target_edge_name,
                    state_json=cur_state,
                )
                additions = import_summary.get("imported", [])
                skipped_imports = import_summary.get("skipped", [])
                if additions:
                    logger.info(
                        "drift_sync: auto-imported %d resources for %s: %s",
                        len(additions), deployment_id,
                        [a.get("tf_name") for a in additions],
                    )
                if skipped_imports:
                    logger.warning(
                        "drift_sync: %d import(s) skipped for %s: %s",
                        len(skipped_imports), deployment_id, skipped_imports,
                    )
            except Exception as exc:
                logger.exception(
                    "drift_sync: auto-import failed for %s: %s",
                    deployment_id, exc,
                )
                # Fallback: surface at least count-based hints so admin is
                # aware something is unmanaged.
                try:
                    additions = await _addition_count_hints(
                        workspace, deployment, runner,
                    )
                except Exception:
                    additions = []

            has_changes = bool(modifications or deletions or additions)
            resolution = None if has_changes else "accepted"
            auto_resolved = not has_changes

            # Snapshot if state changed: TF-detected drift (rc==2), ENF-removed
            # ghosts, or newly-imported unmanaged resources.
            snapshot_version_id: uuid.UUID | None = None
            need_snapshot = (
                plan_result.return_code == 2
                or bool(enf_removed)
                or bool(additions)
            )
            if need_snapshot:
                try:
                    imported_summary = (
                        f" imports={len(additions)}" if additions else ""
                    )
                    snap = await version_store.snapshot_version(
                        db, deployment_id, workspace,
                        source="drift",
                        created_by=f"drift:{triggered_by}{imported_summary}",
                        force_new=True,
                    )
                    if snap is not None:
                        snapshot_version_id = snap.id
                except Exception:
                    logger.exception(
                        "drift_sync: snapshot failed for %s", deployment_id,
                    )

            report = await _write_report(
                db, deployment_id,
                has_changes=has_changes,
                additions=additions,
                modifications=modifications,
                deletions=deletions,
                auto_resolved=auto_resolved,
                resolution=resolution,
                error=None,
                version_id=snapshot_version_id,
            )
            # needs_review only for actionable drift (mods/dels).
            # Addition hints are diagnostic — count-based, count mismatch
            # may be permanent (unmanaged VCD resources) and shouldn't
            # loop the review state.
            if modifications or deletions:
                deployment.needs_review = True
            deployment.last_drift_check = datetime.now(timezone.utc)
            await db.commit()

            logger.info(
                "drift_sync: deployment=%s has_changes=%s mods=%d dels=%d addHints=%d (trigger=%s)",
                deployment_id, has_changes, len(modifications), len(deletions),
                len(additions), triggered_by,
            )
            return report.id
        finally:
            await release_org_lock(deployment.target_org, str(op_id))
            if settings.workspace_cleanup_enabled and workspace.exists():
                try:
                    shutil.rmtree(workspace)
                except Exception:
                    logger.warning("drift_sync: workspace cleanup failed for %s", workspace)


async def sync_all_deployments(triggered_by: str = "cron") -> dict:
    """Run drift sync for every deployment row. Sequential to limit VCD load."""
    logger.info("drift_sync: sweep starting (trigger=%s)", triggered_by)
    async with async_session() as db:
        rows = await db.execute(select(Deployment.id))
        ids = [r[0] for r in rows.all()]

    results = {"total": len(ids), "ok": 0, "failed": 0, "report_ids": []}
    for did in ids:
        try:
            rid = await sync_deployment(did, triggered_by=triggered_by)
            results["ok"] += 1
            results["report_ids"].append(str(rid))
        except Exception as exc:
            logger.exception("drift_sync: deployment %s crashed: %s", did, exc)
            results["failed"] += 1
    logger.info(
        "drift_sync: sweep complete ok=%d failed=%d total=%d",
        results["ok"], results["failed"], results["total"],
    )
    return results
