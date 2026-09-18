"""Cloud-to-cloud migration: NSX-T edge on one VCD → NSX-T edge on another.

Distinct from ``migration.py``, which translates NSX-V (XML, legacy VCD)
into NSX-T.  Here both ends already speak NSX-T, so nothing is translated:
we read the source edge into a ``DeploymentSpec``, point that spec at the
destination edge, and render HCL with the same builder the editor uses.

The two clouds are ``primary`` (``VCD_*``) and ``secondary``
(``SECONDARY_VCD_*``).  Either may be the source or the destination.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthenticatedUser, require_roles
from app.config import settings
from app.core.aria_attribution import Attribution, retag_hcl
from app.core.locking import (
    acquire_org_lock,
    get_org_lock_holder,
    release_org_lock,
)
from app.core.tf_runner import TerraformRunner
from app.core.tf_workspace import TerraformWorkspace
from app.database import get_db
from app.models.operation import Operation, OperationStatus, OperationType
from app.core.deployment_builder import build_hcl, summary_from_spec
from app.core.edge_reader import EdgeReadError, read_edge_spec, retarget
from app.core.ip_remap import apply_mapping, collect_addresses
from app.integrations.vcd_client import PRIMARY, SECONDARY, get_vcd_client
from app.schemas.deployment_spec import DeploymentSpec, TargetSpec

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cloud-migration", tags=["cloud-migration"])

_READ_ROLES = require_roles("tf-admin", "tf-operator", "tf-viewer")
_WRITE_ROLES = require_roles("tf-admin", "tf-operator")


# ---------------------------------------------------------------------------
#  Schemas
# ---------------------------------------------------------------------------

class CloudInfo(BaseModel):
    id: str
    label: str
    url: str
    configured: bool


class CloudList(BaseModel):
    items: list[CloudInfo]


class PreviewRequest(BaseModel):
    """Everything needed to read one edge and aim it at another."""

    source_cloud: str = Field(..., pattern=f"^({PRIMARY}|{SECONDARY})$")
    source_org: str = Field(..., min_length=1)
    source_vdc: str = Field("", description="Display only — not used for reading")
    source_vdc_id: str = Field("", description="Display only — not used for reading")
    source_edge_id: str = Field(..., min_length=1)
    source_edge_name: str | None = None

    target_cloud: str = Field(..., pattern=f"^({PRIMARY}|{SECONDARY})$")
    target_org: str = Field(..., min_length=1)
    target_vdc: str = Field(..., min_length=1)
    target_vdc_id: str = Field(..., min_length=1)
    target_edge_id: str = Field(..., min_length=1)
    target_edge_name: str | None = None

    ip_mapping: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Old address -> new address. The destination cloud allocates its "
            "own public IPs, so NAT rules and IP sets naming the source "
            "address have to be rewritten."
        ),
    )

    @model_validator(mode="after")
    def _check_distinct(self) -> "PreviewRequest":
        if self.source_cloud == self.target_cloud and (
            self.source_edge_id == self.target_edge_id
        ):
            raise ValueError("Source and destination are the same edge on the same cloud")
        return self


class AddressUse(BaseModel):
    address: str
    kind: str
    occurrences: int
    used_by: list[str]


class PreviewResponse(BaseModel):
    hcl: str
    summary: dict
    warnings: list[str]
    spec: DeploymentSpec
    # Addresses found in the source, so the UI can offer a remap table
    # instead of making someone grep the generated HCL.
    addresses: list[AddressUse]


# ---------------------------------------------------------------------------
#  Endpoints
# ---------------------------------------------------------------------------

@router.get("/clouds", response_model=CloudList)
async def list_clouds(
    user: AuthenticatedUser = Depends(_READ_ROLES),  # noqa: ARG001
) -> CloudList:
    """Which clouds this installation can talk to.

    The secondary is reported even when unconfigured so the UI can explain
    why it is greyed out instead of silently hiding it.
    """
    items = [
        CloudInfo(
            id=PRIMARY,
            label="Primary VCD",
            url=settings.vcd_url,
            configured=bool(settings.vcd_url),
        ),
        CloudInfo(
            id=SECONDARY,
            label=settings.secondary_vcd_label,
            url=settings.secondary_vcd_url,
            configured=bool(settings.secondary_vcd_url),
        ),
    ]
    return CloudList(items=items)


def _collect_warnings(spec: DeploymentSpec) -> list[str]:
    """Things that will not survive the trip, surfaced before apply.

    Names are the join key across clouds, so anything nameless or
    referring to a profile we could not name is a real risk, not noise.
    """
    warnings: list[str] = []

    known_profiles = {p.name for p in spec.app_port_profiles}
    known_ip_sets = {s.name for s in spec.ip_sets}
    # Platform profiles are referenced through a data source rather than
    # recreated, so they are expected — but only if the destination has one
    # by the same name, which is worth saying out loud once.
    platform_profiles = {
        p.name for p in spec.app_port_profiles if p.scope != "TENANT"
    }
    if platform_profiles:
        warnings.append(
            "Looked up on the destination by name, not copied: "
            + ", ".join(sorted(platform_profiles))
            + ". The apply fails if the destination has no profile so named."
        )

    for r in spec.nat_rules:
        if not r.name:
            warnings.append("A NAT rule has no name — it cannot be matched on the destination")
        if r.app_port_profile_name and r.app_port_profile_name not in known_profiles:
            warnings.append(
                f"NAT rule {r.name!r} points at app port profile "
                f"{r.app_port_profile_name!r}, which was not found on the source — "
                "the rule would be created with no port restriction at all"
            )

    for r in spec.firewall_rules:
        for ref in r.source_ip_set_names + r.destination_ip_set_names:
            if ref not in known_ip_sets:
                warnings.append(
                    f"Firewall rule {r.name!r} references IP set {ref!r} "
                    "that was not read from the source edge"
                )
        for ref in r.app_port_profile_names:
            if ref not in known_profiles:
                warnings.append(
                    f"Firewall rule {r.name!r} references app port profile {ref!r}, "
                    "which was not found on the source — the rule would be created "
                    "without that port restriction"
                )

    if not any([spec.ip_sets, spec.nat_rules, spec.firewall_rules, spec.static_routes]):
        warnings.append("The source edge has no NAT, firewall, IP sets or static routes")

    # De-duplicate while keeping order — the same profile can trip many rules.
    seen: set[str] = set()
    return [w for w in warnings if not (w in seen or seen.add(w))]


@router.post("/preview", response_model=PreviewResponse)
async def preview(
    body: PreviewRequest,
    user: AuthenticatedUser = Depends(_WRITE_ROLES),
) -> PreviewResponse:
    """Read the source edge and render HCL aimed at the destination edge."""
    logger.info(
        "user=%s action=cloud_migration_preview src_cloud=%s src_edge=%s "
        "dst_cloud=%s dst_edge=%s ip_remaps=%d",
        user.username, body.source_cloud, body.source_edge_id,
        body.target_cloud, body.target_edge_id, len(body.ip_mapping),
    )

    try:
        source = get_vcd_client(body.source_cloud)
        get_vcd_client(body.target_cloud)  # fail early if destination is unconfigured
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        spec = await read_edge_spec(
            source,
            org_name=body.source_org,
            vdc_name=body.source_vdc,
            vdc_id=body.source_vdc_id,
            edge_id=body.source_edge_id,
            edge_name=body.source_edge_name,
        )
    except EdgeReadError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    # Addresses are reported from the source, before any rewriting, so the
    # table the operator sees matches what is actually on the source edge.
    addresses = collect_addresses(spec)

    try:
        spec = apply_mapping(spec, body.ip_mapping)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    aimed = retarget(spec, TargetSpec(
        org=body.target_org,
        vdc=body.target_vdc,
        vdc_id=body.target_vdc_id,
        edge_id=body.target_edge_id,
        edge_name=body.target_edge_name,
    ))

    hcl = build_hcl(aimed)
    # summary_from_spec() does not count IP sets — they matter here because
    # firewall rules reference them by name across clouds.
    summary = {**summary_from_spec(aimed), "ip_sets_total": len(aimed.ip_sets)}
    warnings = _collect_warnings(aimed)
    unmapped = [
        a["address"] for a in addresses
        if a["kind"] == "external" and a["address"] not in body.ip_mapping
    ]
    if unmapped:
        warnings.insert(0, (
            "Public address still pointing at the source cloud: "
            + ", ".join(unmapped)
            + ". The destination does not own it, so those NAT rules will not work."
        ))

    return PreviewResponse(
        hcl=hcl,
        summary=summary,
        warnings=warnings,
        spec=aimed,
        addresses=[AddressUse(**a) for a in addresses],
    )


# ---------------------------------------------------------------------------
#  Terraform: plan and apply against the destination cloud
# ---------------------------------------------------------------------------

class PlanRequest(BaseModel):
    target_cloud: str = Field(..., pattern=f"^({PRIMARY}|{SECONDARY})$")
    target_org: str = Field(..., min_length=1)
    target_vdc: str = Field("", description="Recorded for the operator, not used by terraform")
    target_edge_id: str = Field(..., min_length=1)
    target_edge_name: str | None = None
    hcl: str = Field(..., min_length=1)


class ApplyRequest(BaseModel):
    target_cloud: str = Field(..., pattern=f"^({PRIMARY}|{SECONDARY})$")
    target_org: str = Field(..., min_length=1)
    plan_operation_id: uuid.UUID = Field(
        ..., description="The plan whose workspace (and plan.bin) to apply"
    )


class OperationStarted(BaseModel):
    operation_id: uuid.UUID


def _lock_scope(cloud: str, org: str) -> str:
    """Lock and workspace name.

    The org lock is keyed by name only, and the same org name routinely
    exists on both clouds -- CLT_ADAMANT_SYSTEMS is on each. Without the
    cloud in the key, work on one cloud would block the other for no
    reason, and two runs against the *same* edge would share a directory.
    """
    return f"{cloud}-{org}"


def _state_key(cloud: str, edge_id: str) -> str:
    """Terraform state location for one edge on one cloud.

    Deliberately not the deployment state key: these resources live on a
    cloud the Deployment table cannot express yet, and sharing a key would
    let the nightly drift job reconcile them against the wrong VCD.
    """
    edge_slug = edge_id.rsplit(":", 1)[-1] or "edge"
    return f"cloud-migration/{cloud}/{edge_slug}/terraform.tfstate"


def _write_workspace(
    cloud: str,
    org: str,
    operation_id: uuid.UUID,
    edge_id: str,
    hcl: str,
    username: str,
) -> TerraformWorkspace:
    """Materialise main.tf and a provider aimed at the destination cloud."""
    creds = settings.cloud_credentials(cloud)
    workspace = TerraformWorkspace(_lock_scope(cloud, org), operation_id)
    workspace.work_dir.mkdir(parents=True, exist_ok=True)

    tagged = retag_hcl(
        hcl, Attribution(kc_username=username or "unknown", op_id=str(operation_id))
    )
    (workspace.work_dir / "main.tf").write_text(tagged, encoding="utf-8")

    tpl_dir = Path(__file__).resolve().parents[3] / "templates" / "migration"
    jenv = Environment(
        loader=FileSystemLoader(str(tpl_dir)),
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    (workspace.work_dir / "provider.tf").write_text(
        jenv.get_template("provider.tf.j2").render(
            state_key=_state_key(cloud, edge_id),
            sysorg=creds["org"] or "System",
        ),
        encoding="utf-8",
    )
    return workspace


async def _finish(operation_id: uuid.UUID, lock_name: str, result, plan_output: str = "") -> None:
    """Record the outcome and always let go of the lock."""
    from app.database import async_session

    try:
        async with async_session() as db:
            op = await db.get(Operation, operation_id)
            if op is not None:
                op.status = (
                    OperationStatus.SUCCESS if result.success else OperationStatus.FAILED
                )
                op.completed_at = datetime.now(timezone.utc)
                if plan_output:
                    op.plan_output = plan_output
                if not result.success:
                    op.error_message = result.stderr
                await db.commit()
    finally:
        await release_org_lock(lock_name, str(operation_id))


async def _run_plan(
    operation_id: uuid.UUID, lock_name: str, workspace: TerraformWorkspace, cloud: str
) -> None:
    """init then plan. No pre-apply imports: that helper reads the primary
    VCD, which is not necessarily the cloud we are writing to."""
    runner = TerraformRunner(
        workspace.work_dir, operation_id=str(operation_id), cloud=cloud
    )
    init = await runner.init()
    if not init.success:
        await _finish(operation_id, lock_name, init)
        return
    result = await runner.plan()
    await _finish(operation_id, lock_name, result, plan_output=result.stdout)


async def _run_apply(
    operation_id: uuid.UUID, lock_name: str, workspace: TerraformWorkspace, cloud: str
) -> None:
    runner = TerraformRunner(
        workspace.work_dir, operation_id=str(operation_id), cloud=cloud
    )
    result = await runner.apply()
    await _finish(operation_id, lock_name, result, plan_output=result.stdout)


@router.post("/plan", response_model=OperationStarted)
async def plan(
    body: PlanRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_WRITE_ROLES),
) -> OperationStarted:
    """Run init + plan against the destination cloud.

    Returns immediately so the UI can open the log WebSocket before output
    starts arriving.
    """
    try:
        settings.cloud_credentials(body.target_cloud)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    operation_id = uuid.uuid4()
    lock_name = _lock_scope(body.target_cloud, body.target_org)

    logger.info(
        "user=%s action=cloud_migration_plan cloud=%s org=%s edge=%s operation_id=%s",
        user.username, body.target_cloud, body.target_org,
        body.target_edge_id, operation_id,
    )

    if not await acquire_org_lock(lock_name, str(operation_id)):
        holder = await get_org_lock_holder(lock_name)
        raise HTTPException(
            status_code=409,
            detail=(
                f"'{body.target_org}' on {body.target_cloud} is locked by "
                f"operation {holder}. Wait for it to finish."
            ),
        )

    db.add(Operation(
        id=operation_id,
        type=OperationType.PLAN,
        status=OperationStatus.RUNNING,
        user_id=user.sub,
        username=user.username,
        target_org=body.target_org,
        target_edge_id=body.target_edge_id,
    ))
    await db.commit()

    try:
        workspace = _write_workspace(
            body.target_cloud, body.target_org, operation_id,
            body.target_edge_id, body.hcl, user.username,
        )
    except Exception as exc:
        logger.exception("cloud migration workspace failed for %s", operation_id)
        op = await db.get(Operation, operation_id)
        if op is not None:
            op.status = OperationStatus.FAILED
            op.error_message = str(exc)
            op.completed_at = datetime.now(timezone.utc)
            await db.commit()
        await release_org_lock(lock_name, str(operation_id))
        raise HTTPException(status_code=500, detail=f"Could not create workspace: {exc}")

    asyncio.create_task(_run_plan(operation_id, lock_name, workspace, body.target_cloud))
    return OperationStarted(operation_id=operation_id)


@router.post("/apply", response_model=OperationStarted)
async def apply(
    body: ApplyRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_WRITE_ROLES),
) -> OperationStarted:
    """Apply the plan produced by ``plan_operation_id``.

    Reuses that run's workspace, which still holds plan.bin, so what gets
    applied is exactly what was reviewed.
    """
    lock_name = _lock_scope(body.target_cloud, body.target_org)
    workspace = TerraformWorkspace(lock_name, body.plan_operation_id)
    if not (workspace.work_dir / "plan.bin").exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "That plan's workspace is gone — plans do not survive a "
                "backend restart or cleanup. Run the plan again."
            ),
        )

    operation_id = uuid.uuid4()
    logger.info(
        "user=%s action=cloud_migration_apply cloud=%s org=%s plan_op=%s operation_id=%s",
        user.username, body.target_cloud, body.target_org,
        body.plan_operation_id, operation_id,
    )

    if not await acquire_org_lock(lock_name, str(operation_id)):
        holder = await get_org_lock_holder(lock_name)
        raise HTTPException(
            status_code=409,
            detail=f"'{body.target_org}' is locked by operation {holder}.",
        )

    db.add(Operation(
        id=operation_id,
        type=OperationType.APPLY,
        status=OperationStatus.RUNNING,
        user_id=user.sub,
        username=user.username,
        target_org=body.target_org,
    ))
    await db.commit()

    asyncio.create_task(_run_apply(operation_id, lock_name, workspace, body.target_cloud))
    return OperationStarted(operation_id=operation_id)
