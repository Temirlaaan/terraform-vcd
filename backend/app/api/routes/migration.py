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
from app.core.locking import acquire_org_lock, get_org_lock_holder, release_org_lock
from app.core.tf_workspace import TerraformWorkspace
from app.database import get_db
from app.integrations.vcd_client import vcd_client
from app.migration.fetcher import LegacyVcdFetcher
from app.migration.generator import MigrationHCLGenerator
from app.migration.normalizer import normalize_edge_snapshot
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

_PROVIDER_TF = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "templates" / "migration" / "provider.tf.j2"
).read_text(encoding="utf-8")


def _create_migration_workspace(
    org_name: str, operation_id: uuid.UUID, hcl: str,
) -> TerraformWorkspace:
    """Create a workspace and write pre-generated HCL + provider config."""
    workspace = TerraformWorkspace(org_name, operation_id)
    workspace.work_dir.mkdir(parents=True, exist_ok=True)
    (workspace.work_dir / "main.tf").write_text(hcl, encoding="utf-8")
    (workspace.work_dir / "provider.tf").write_text(_PROVIDER_TF, encoding="utf-8")
    return workspace


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

    # --- Create DB record ---
    operation = Operation(
        id=operation_id,
        type=OperationType.PLAN,
        status=OperationStatus.RUNNING,
        user_id=user.sub,
        username=user.username,
        target_org=org_name,
    )
    db.add(operation)
    await db.commit()

    # --- Prepare workspace with raw HCL ---
    try:
        workspace = _create_migration_workspace(org_name, operation_id, body.hcl)
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
    asyncio.create_task(_run_plan_task(operation_id, org_name, workspace))
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

    # --- Create apply DB record ---
    operation = Operation(
        id=apply_id,
        type=OperationType.APPLY,
        status=OperationStatus.RUNNING,
        user_id=user.sub,
        username=user.username,
        target_org=org_name,
    )
    db.add(operation)
    await db.commit()

    # Reuse the plan workspace (it still has plan.bin)
    workspace = TerraformWorkspace(org_name, body.operation_id)

    # --- Launch background task (reuse from terraform.py) ---
    asyncio.create_task(_run_apply_task(apply_id, org_name, workspace))
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
