"""API routes for edge migration (NSX-V → NSX-T)."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.terraform import _run_apply_task, _run_plan_task
from app.auth import AuthenticatedUser, require_roles
from app.config import settings
from app.core.locking import acquire_org_lock, get_org_lock_holder, release_org_lock
from app.core.tf_import import run_preapply_imports
from app.core.tf_workspace import TerraformWorkspace
from app.database import get_db
from app.integrations.vcd_client import vcd_client
from app.migration.fetcher import LegacyVcdFetcher
from app.migration.generator import MigrationHCLGenerator
from app.migration.normalizer import normalize_edge_snapshot
from app.models.deployment import Deployment
from app.models.operation import Operation, OperationStatus, OperationType
from app.schemas.migration import (
    MigrationApplyRequest,
    MigrationPlanRequest,
    MigrationPlanResponse,
    MigrationRequest,
    MigrationResponse,
    MigrationSummary,
    TargetCheckResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/migration", tags=["migration"])

_generator = MigrationHCLGenerator()


def _friendly_deployment_name(source_edge_name: str | None, when: datetime) -> str:
    """Build ``<src_edge>_YYYYMMDD`` name, fallback to date-only if no src name."""
    date_part = when.strftime("%Y%m%d")
    if source_edge_name:
        return f"{source_edge_name}_{date_part}"
    return f"migration_{date_part}"


def _friendly_description(
    source_edge_name: str | None,
    target_org: str,
    target_vdc: str | None,
    target_edge_name: str | None,
) -> str:
    src = source_edge_name or "unknown-source"
    org = target_org or ""
    vdc = target_vdc or ""
    edge = target_edge_name or ""
    return f"{src} -> {org}/{vdc}/{edge}"


def _has_ugly_name(name: str | None) -> bool:
    return bool(name) and name.startswith("migration:")


def _summary_from_hcl(hcl: str) -> dict:
    """Fallback summary extraction by counting resource blocks in migration HCL."""
    import re as _re
    fw_match = _re.search(
        r'resource\s+"vcd_nsxt_firewall"\s+"[^"]+"\s*\{(.*?)\n\}',
        hcl, _re.DOTALL,
    )
    fw_rules = len(_re.findall(r'\brule\s*\{', fw_match.group(1))) if fw_match else 0
    app_res = len(_re.findall(r'resource\s+"vcd_nsxt_app_port_profile"', hcl))
    app_data = len(_re.findall(r'data\s+"vcd_nsxt_app_port_profile"', hcl))
    return {
        "firewall_rules_total": fw_rules,
        "firewall_rules_user": fw_rules,
        "firewall_rules_system": 0,
        "nat_rules_total": len(_re.findall(r'resource\s+"vcd_nsxt_nat_rule"', hcl)),
        "app_port_profiles_total": app_res + app_data,
        "app_port_profiles_system": app_data,
        "app_port_profiles_custom": app_res,
        "static_routes_total": len(
            _re.findall(r'resource\s+"vcd_nsxt_edgegateway_static_route"', hcl)
        ),
    }


async def _ensure_migration_deployment(
    db: AsyncSession,
    target_edge_id: str,
    target_org: str,
    hcl: str,
    user: AuthenticatedUser,
    source_edge_name: str | None = None,
    target_vdc: str | None = None,
    target_edge_name: str | None = None,
    source_host: str | None = None,
    source_edge_uuid: str | None = None,
    verify_ssl: bool | None = None,
    summary: dict | None = None,
) -> Deployment:
    """Lookup existing migration deployment for this target edge, or create one.

    The migration flow does not have an explicit "save deployment" step
    before plan/apply; Phase 3 versioning needs a stable ``deployment_id``
    to anchor MinIO snapshots and the ``deployment_versions`` table.

    Lookup is by ``(target_edge_id, kind='migration')``. The first matching
    row wins; subsequent migration plans/applies for the same edge keep
    reusing the same deployment_id (and thus the same state_key).

    If an existing row carries the legacy ugly ``migration:<hex>`` name
    and the caller supplies ``source_edge_name`` / ``target_vdc`` /
    ``target_edge_name``, the row is upgraded in-place to a friendly
    name + description.
    """
    result = await db.execute(
        select(Deployment).where(
            Deployment.target_edge_id == target_edge_id,
            Deployment.kind == "migration",
        ).order_by(Deployment.created_at.asc()).limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.hcl = hcl

        # Backfill source_edge_name
        if source_edge_name and not existing.source_edge_name:
            existing.source_edge_name = source_edge_name

        # Backfill target_edge_name
        if target_edge_name and not existing.target_edge_name:
            existing.target_edge_name = target_edge_name

        # Backfill target_vdc
        if target_vdc and not existing.target_vdc:
            existing.target_vdc = target_vdc

        # Backfill source_host / source_edge_uuid / verify_ssl
        if source_host and not existing.source_host:
            existing.source_host = source_host
        if source_edge_uuid and not existing.source_edge_uuid:
            existing.source_edge_uuid = source_edge_uuid
        if verify_ssl is not None and not existing.verify_ssl:
            existing.verify_ssl = bool(verify_ssl)

        # Backfill summary: prefer provided, else parse HCL if empty.
        if not existing.summary:
            existing.summary = summary or _summary_from_hcl(hcl)
        elif summary:
            existing.summary = summary

        # Upgrade ugly auto-created name
        if _has_ugly_name(existing.name) and source_edge_name:
            existing.name = _friendly_deployment_name(
                source_edge_name, existing.created_at
            )

        # Rebuild description if legacy ("Auto-created by migration plan flow (Phase 3)")
        # or empty — always keep it in friendly format.
        legacy_desc = (
            not existing.description
            or "Phase 3" in (existing.description or "")
            or (existing.description or "").startswith("Auto-created by migration plan flow")
        )
        if legacy_desc and source_edge_name:
            existing.description = _friendly_description(
                source_edge_name, target_org, target_vdc,
                target_edge_name or existing.target_edge_name,
            )

        await db.commit()
        return existing

    now = datetime.now(timezone.utc)
    dep = Deployment(
        name=_friendly_deployment_name(source_edge_name, now),
        kind="migration",
        description=_friendly_description(
            source_edge_name, target_org, target_vdc, target_edge_name
        ),
        source_host=source_host or "",
        source_edge_uuid=source_edge_uuid or "",
        source_edge_name=source_edge_name or "",
        verify_ssl=bool(verify_ssl) if verify_ssl is not None else False,
        target_org=target_org,
        target_vdc=target_vdc or "",
        target_vdc_id="",
        target_edge_id=target_edge_id,
        target_edge_name=target_edge_name,
        hcl=hcl,
        summary=summary or _summary_from_hcl(hcl),
        created_by=user.username,
    )
    db.add(dep)
    await db.commit()
    await db.refresh(dep)
    logger.info(
        "auto-created migration deployment id=%s name=%s edge=%s by=%s",
        dep.id, dep.name, target_edge_id, user.username,
    )
    return dep


def _build_summary(normalized: dict) -> MigrationSummary:
    """Extract summary counts from normalized JSON."""
    fw = normalized.get("firewall", {})
    fw_rules = fw.get("rules", [])
    user_rules = [r for r in fw_rules if not r.get("is_system", False)]
    system_rules = [r for r in fw_rules if r.get("is_system", False)]

    nat = normalized.get("nat", {})
    profiles = nat.get("required_app_port_profiles", [])
    system_profiles = [p for p in profiles if p.get("is_system_defined", False)]

    routing = normalized.get("routing", {})

    return MigrationSummary(
        firewall_rules_total=len(fw_rules),
        firewall_rules_user=len(user_rules),
        firewall_rules_system=len(system_rules),
        nat_rules_total=len(nat.get("rules", [])),
        app_port_profiles_total=len(profiles),
        app_port_profiles_system=len(system_profiles),
        app_port_profiles_custom=len(profiles) - len(system_profiles),
        static_routes_total=len(routing.get("static_routes", [])),
    )


@router.post("/generate", response_model=MigrationResponse)
async def generate_migration_hcl(
    body: MigrationRequest,
    user: AuthenticatedUser = Depends(require_roles("tf-admin", "tf-operator")),
) -> MigrationResponse:
    """Fetch edge config from legacy VCD, normalize, and generate HCL.

    Full pipeline: fetch XML → normalize → generate HCL → return.
    """
    logger.info(
        "user=%s action=migration_generate edge_uuid=%s host=%s",
        user.username, body.edge_uuid, body.host,
    )

    # 1. Fetch raw XML from legacy VCD
    fetcher = LegacyVcdFetcher(
        host=body.host,
        api_token=body.api_token,
        verify_ssl=body.verify_ssl,
    )
    try:
        raw_xmls = await fetcher.fetch_edge_snapshot(body.edge_uuid)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 401 or status == 403:
            logger.warning("Legacy VCD auth failed: %s", status)
            raise HTTPException(
                status_code=401,
                detail="Authentication failed on legacy VCD. Check credentials.",
            )
        logger.error("Legacy VCD request failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Legacy VCD returned HTTP {status}. Check host and edge UUID.",
        )
    except httpx.ConnectError:
        logger.error("Cannot connect to legacy VCD at %s", body.host)
        raise HTTPException(
            status_code=502,
            detail=f"Cannot connect to legacy VCD at {body.host}.",
        )
    except ValueError as exc:
        logger.error("Legacy VCD login error: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    # 2. Normalize XML → canonical JSON
    try:
        normalized = normalize_edge_snapshot(raw_xmls)
    except Exception as exc:
        logger.error("XML normalization failed: %s", exc)
        raise HTTPException(
            status_code=400,
            detail=f"Failed to parse edge gateway XML: {exc}",
        )

    # 3. Generate HCL
    try:
        hcl = _generator.generate(
            normalized,
            target_org=body.target_org,
            target_vdc=body.target_vdc,
            target_vdc_id=body.target_vdc_id,
            target_edge_id=body.target_edge_id,
        )
    except Exception as exc:
        logger.error("HCL generation failed: %s", exc)
        raise HTTPException(
            status_code=422,
            detail="HCL generation failed. Check normalized data.",
        )

    edge_name = normalized.get("edge", {}).get("name", "")
    summary = _build_summary(normalized)

    logger.info(
        "user=%s action=migration_generate edge_name=%s rules=%d nat=%d routes=%d",
        user.username, edge_name,
        summary.firewall_rules_user, summary.nat_rules_total, summary.static_routes_total,
    )

    return MigrationResponse(hcl=hcl, edge_name=edge_name, summary=summary)


# ------------------------------------------------------------------
#  Plan / Apply for migration HCL
# ------------------------------------------------------------------

from jinja2 import Environment, FileSystemLoader

_MIGRATION_TEMPLATES_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent / "templates" / "migration"
)
_MIGRATION_JINJA = Environment(
    loader=FileSystemLoader(str(_MIGRATION_TEMPLATES_DIR)),
    autoescape=False,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)


def _state_key_for_deployment(deployment_id: uuid.UUID) -> str:
    """Phase 3: live state key per deployment_id.

    All terraform plan/apply runs for the same deployment share this key
    so re-runs reuse state instead of recreating resources. Per-version
    snapshots live under ``deployments/<id>/v<N>/`` (see version_store).
    """
    return f"deployments/{deployment_id}/current/terraform.tfstate"


def _render_provider_tf(deployment_id: uuid.UUID) -> str:
    """Render provider.tf.j2 with S3 backend pointing to deployment current/ key."""
    tpl = _MIGRATION_JINJA.get_template("provider.tf.j2")
    return tpl.render(state_key=_state_key_for_deployment(deployment_id))


def _create_migration_workspace(
    org_name: str, operation_id: uuid.UUID, hcl: str, deployment_id: uuid.UUID,
) -> TerraformWorkspace:
    """Create a workspace and write pre-generated HCL + provider config.

    Phase 3: provider.tf state_key derives from ``deployment_id`` so all
    plan/apply/rollback runs for the same deployment share state.
    """
    workspace = TerraformWorkspace(org_name, operation_id)
    workspace.work_dir.mkdir(parents=True, exist_ok=True)
    (workspace.work_dir / "main.tf").write_text(hcl, encoding="utf-8")
    (workspace.work_dir / "provider.tf").write_text(
        _render_provider_tf(deployment_id), encoding="utf-8"
    )
    return workspace


async def _run_migration_plan_task(
    operation_id: uuid.UUID,
    org_name: str,
    workspace: TerraformWorkspace,
    target_edge_id: str,
) -> None:
    """Migration-specific plan task: init -> preapply_imports -> plan.

    Runs `terraform import` for any HCL resource whose name matches an
    existing VCD entity on the target edge/org, so `terraform plan` does
    not try to create duplicates.
    """
    from app.core.tf_runner import TerraformRunner, log_channel
    from app.models.operation import OperationStatus
    from app.database import async_session
    from sqlalchemy import select
    from datetime import datetime, timezone
    from redis.asyncio import Redis

    redis = None
    try:
        if operation_id:
            redis = Redis.from_url(settings.redis_url, decode_responses=True)
            ch = log_channel(str(operation_id))
            await redis.publish(ch, "[stdout] [phase1] terraform init")

        async with async_session() as db:
            result = await db.execute(
                select(Operation).where(Operation.id == operation_id)
            )
            op = result.scalar_one()

            runner = TerraformRunner(workspace.work_dir, operation_id=str(operation_id))

            init_result = await runner.init()
            if not init_result.success:
                op.status = OperationStatus.FAILED
                op.error_message = init_result.stderr
                op.completed_at = datetime.now(timezone.utc)
                await db.commit()
                return

            if redis:
                await redis.publish(ch, "[stdout] [phase2] scanning VCD for existing resources")

            try:
                imported, errs = await run_preapply_imports(
                    workspace.work_dir,
                    target_edge_id,
                    org_name,
                    operation_id=str(operation_id),
                )
                if redis:
                    if imported:
                        await redis.publish(ch, f"[stdout] [phase2] imported {imported} existing resources into state")
                    for e in errs:
                        await redis.publish(ch, f"[stderr] [phase2] {e}")
            except Exception as exc:
                logger.exception("pre-apply import failed for %s", operation_id)
                if redis:
                    await redis.publish(ch, f"[stderr] [phase2] import orchestrator crashed: {exc}")

            if redis:
                await redis.publish(ch, "[stdout] [phase3] terraform plan")

            plan_result = await runner.plan()
            op.plan_output = plan_result.stdout
            if plan_result.success:
                op.status = OperationStatus.SUCCESS
            else:
                op.status = OperationStatus.FAILED
                op.error_message = plan_result.stderr
            op.completed_at = datetime.now(timezone.utc)
            await db.commit()

    except Exception as exc:
        logger.exception("_run_migration_plan_task failed for %s", operation_id)
        try:
            async with async_session() as edb:
                result = await edb.execute(
                    select(Operation).where(Operation.id == operation_id)
                )
                op = result.scalar_one()
                op.status = OperationStatus.FAILED
                op.error_message = f"Internal error: {type(exc).__name__}: {exc}"
                op.completed_at = datetime.now(timezone.utc)
                await edb.commit()
        except Exception:
            logger.exception("failed to update op %s after error", operation_id)
    finally:
        if redis:
            try:
                await redis.aclose()
            except Exception:
                pass
        await release_org_lock(org_name, str(operation_id))


@router.post("/plan", response_model=MigrationPlanResponse)
async def migration_plan(
    body: MigrationPlanRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(require_roles("tf-admin", "tf-operator")),
) -> MigrationPlanResponse:
    """Write pre-generated HCL to workspace and run terraform init + plan.

    Returns the operation_id immediately so the frontend can connect
    a WebSocket before terraform output begins streaming.
    """
    org_name = body.target_org
    operation_id = uuid.uuid4()

    logger.info(
        "user=%s action=migration_plan org=%s operation_id=%s",
        user.username, org_name, operation_id,
    )

    # --- Acquire distributed lock ---
    locked = await acquire_org_lock(org_name, str(operation_id))
    if not locked:
        holder = await get_org_lock_holder(org_name)
        logger.warning(
            "Org %s locked by %s, rejecting migration plan from %s",
            org_name, holder, user.username,
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"Organisation '{org_name}' is locked by operation {holder}. "
                "Wait for it to finish or release the lock."
            ),
        )

    # --- Phase 3: ensure a Deployment row exists for this target edge ---
    deployment = await _ensure_migration_deployment(
        db, body.target_edge_id, org_name, body.hcl, user,
        source_edge_name=body.source_edge_name,
        target_vdc=body.target_vdc,
        target_edge_name=body.target_edge_name,
        source_host=body.source_host,
        source_edge_uuid=body.source_edge_uuid,
        verify_ssl=body.verify_ssl,
        summary=body.summary,
    )

    # --- Create DB record ---
    operation = Operation(
        id=operation_id,
        type=OperationType.PLAN,
        status=OperationStatus.RUNNING,
        user_id=user.sub,
        username=user.username,
        target_org=org_name,
        deployment_id=deployment.id,
        target_edge_id=body.target_edge_id,
    )
    db.add(operation)
    await db.commit()

    # --- Prepare workspace with raw HCL ---
    try:
        workspace = _create_migration_workspace(org_name, operation_id, body.hcl, deployment.id)
    except Exception as exc:
        logger.exception("Failed to create migration workspace for plan %s", operation_id)
        operation.status = OperationStatus.FAILED
        operation.error_message = str(exc)
        operation.completed_at = datetime.now(timezone.utc)
        await db.commit()
        await release_org_lock(org_name, str(operation_id))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create workspace for operation {operation_id}.",
        )

    # --- Launch background task (reuse from terraform.py) ---
    asyncio.create_task(
        _run_migration_plan_task(operation_id, org_name, workspace, body.target_edge_id)
    )
    return MigrationPlanResponse(operation_id=operation_id)


@router.post("/apply", response_model=MigrationPlanResponse)
async def migration_apply(
    body: MigrationApplyRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(require_roles("tf-admin", "tf-operator")),
) -> MigrationPlanResponse:
    """Launch terraform apply for a previously successful migration plan.

    Returns the operation_id immediately so the frontend can connect
    a WebSocket before terraform output begins streaming.
    """
    # --- Fetch the plan operation ---
    result = await db.execute(
        select(Operation).where(Operation.id == body.operation_id)
    )
    plan_op = result.scalar_one_or_none()
    if not plan_op:
        raise HTTPException(status_code=404, detail="Plan operation not found")
    if plan_op.status != OperationStatus.SUCCESS:
        raise HTTPException(status_code=400, detail="Can only apply a successful plan")

    org_name = plan_op.target_org
    apply_id = uuid.uuid4()

    logger.info(
        "user=%s action=migration_apply org=%s plan_id=%s apply_id=%s",
        user.username, org_name, body.operation_id, apply_id,
    )

    # --- Acquire distributed lock ---
    locked = await acquire_org_lock(org_name, str(apply_id))
    if not locked:
        holder = await get_org_lock_holder(org_name)
        logger.warning(
            "Org %s locked by %s, rejecting migration apply from %s",
            org_name, holder, user.username,
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"Organisation '{org_name}' is locked by operation {holder}. "
                "Wait for it to finish or release the lock."
            ),
        )

    # --- Create apply DB record (carry deployment_id from plan) ---
    operation = Operation(
        id=apply_id,
        type=OperationType.APPLY,
        status=OperationStatus.RUNNING,
        user_id=user.sub,
        username=user.username,
        target_org=org_name,
        deployment_id=plan_op.deployment_id,
        target_edge_id=plan_op.target_edge_id,
    )
    db.add(operation)
    await db.commit()

    # Reuse the plan workspace (it still has plan.bin)
    workspace = TerraformWorkspace(org_name, body.operation_id)

    # --- Launch background task; pass deployment_id so Phase 3 snapshot fires ---
    asyncio.create_task(_run_apply_task(
        apply_id, org_name, workspace,
        deployment_id=plan_op.deployment_id,
        version_source="apply",
        version_user=user.username,
    ))
    return MigrationPlanResponse(operation_id=apply_id)


@router.get("/target-check", response_model=TargetCheckResponse)
async def migration_target_check(
    edge_id: str = Query(..., min_length=1, description="Target NSX-T edge gateway URN"),
    user: AuthenticatedUser = Depends(
        require_roles("tf-admin", "tf-operator", "tf-viewer")
    ),
) -> TargetCheckResponse:
    """Inspect the target NSX-T edge gateway before migration.

    Returns counts of IP sets, NAT rules, firewall rules, and static routes
    currently present on the target edge so the user can confirm they won't
    overwrite or duplicate existing configuration.
    """
    logger.info(
        "user=%s action=migration_target_check edge_id=%s",
        user.username, edge_id,
    )

    ip_sets, nat_rules, fw_rules, routes = await asyncio.gather(
        vcd_client.count_ip_sets_on_edge(edge_id),
        vcd_client.count_nat_rules_on_edge(edge_id),
        vcd_client.count_firewall_rules_on_edge(edge_id),
        vcd_client.count_static_routes_on_edge(edge_id),
    )

    return TargetCheckResponse(
        ip_sets_count=ip_sets,
        nat_rules_count=nat_rules,
        firewall_rules_count=fw_rules,
        static_routes_count=routes,
    )
