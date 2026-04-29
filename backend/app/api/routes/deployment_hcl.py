"""Deployment HCL editor + re-apply endpoints (admin/operator).

  GET  /deployments/{id}/hcl                → latest ``main.tf`` as plaintext
  POST /deployments/{id}/plan   {hcl: str}  → run terraform plan with given HCL
  POST /deployments/{id}/apply  {operation_id: UUID}
                                            → apply previously successful plan

Workspace uses the deployment's live state key (S3 backend), so state
mutations land in ``deployments/<id>/current/terraform.tfstate``.
Successful apply is snapshotted into a new ``deployment_versions`` row.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthenticatedUser, require_roles
from app.core import minio_client
from app.core.aria_attribution import Attribution, retag_hcl, strip_descriptions_in_hcl
from app.core import version_store
from app.core.deployment_state_align import scan_and_remove_orphans
from app.core.locking import acquire_org_lock, release_org_lock, get_org_lock_holder
from app.core.tf_workspace import TerraformWorkspace
from app.database import get_db
from app.models.deployment import Deployment
from app.models.deployment_version import DeploymentVersion
from app.models.operation import Operation, OperationStatus, OperationType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deployments", tags=["deployment-hcl"])

# M-BE Variant B: viewer no longer reads HCL. Network topology disclosure
# (target VDC/edge URNs, NAT external IPs, IP-set CIDRs, firewall rules)
# is too risky for a read-only role. Both edit and read endpoints now
# require operator+admin.
_EDIT_ROLES = require_roles("tf-admin", "tf-operator")
_READ_ROLES = require_roles("tf-admin", "tf-operator")


import re

_EDGE_LIT_RE = re.compile(r'edge_gateway_id\s*=\s*"([^"]+)"')
_ORG_LIT_RE = re.compile(r'(?<![A-Za-z_])org\s*=\s*"([^"]+)"')
_VDC_LIT_RE = re.compile(r'(?<![A-Za-z_])vdc(?:_id)?\s*=\s*"([^"]+)"')


def _validate_hcl_binding(hcl: str, deployment: "Deployment") -> None:
    """H2-BE: reject HCL that hard-codes target identifiers different
    from the deployment row's bound target.

    Variable references (``var.target_edge_id``) and unquoted values are
    not matched by the regexes — only literal ``"..."`` strings. This
    blocks an operator from submitting HCL that addresses someone else's
    edge while the dashboard's System Administrator service account
    obediently applies it.
    """
    for label, pattern, expected in (
        ("edge_gateway_id", _EDGE_LIT_RE, deployment.target_edge_id),
        ("org", _ORG_LIT_RE, deployment.target_org),
        ("vdc / vdc_id", _VDC_LIT_RE, deployment.vdc_id or deployment.target_vdc),
    ):
        if expected is None:
            continue
        for match in pattern.finditer(hcl):
            value = match.group(1)
            if value != expected:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"HCL binding violation: {label}={value!r} does not "
                        f"match deployment target {expected!r}. "
                        "Use var.target_edge_id / var.target_org / var.vdc_id "
                        "to reference the bound target instead of literals."
                    ),
                )


class DeploymentPlanBody(BaseModel):
    hcl: str


class DeploymentApplyBody(BaseModel):
    operation_id: uuid.UUID


class OperationIdResponse(BaseModel):
    operation_id: uuid.UUID


def _render_provider_tf(deployment_id: uuid.UUID) -> str:
    from jinja2 import Environment, FileSystemLoader

    tpl_dir = (
        Path(__file__).resolve().parent.parent.parent.parent / "templates" / "migration"
    )
    jenv = Environment(
        loader=FileSystemLoader(str(tpl_dir)),
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    tpl = jenv.get_template("provider.tf.j2")
    return tpl.render(
        state_key=version_store.state_key_for_deployment(deployment_id)
    )


@router.get("/{deployment_id}/hcl", response_class=PlainTextResponse)
async def get_deployment_hcl(
    deployment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_READ_ROLES),
) -> str:
    """Return the deployment's current main.tf as plaintext.

    Source: ``deployment.hcl`` DB column, which is the live draft kept
    in sync by POST /manual, PUT /spec and migration rebuild. Version
    snapshots (immutable history) are served via
    ``/deployments/{id}/versions/{n}/hcl`` instead.

    Before: this endpoint returned the latest ``DeploymentVersion``
    snapshot from MinIO, which made editor Save appear no-op — versions
    are only created on successful apply (Phase 3), so PUT /spec edits
    were invisible in the HCL tab until a Plan+Apply cycle completed.
    """
    deployment = await db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return strip_descriptions_in_hcl(deployment.hcl or "")


@router.post("/{deployment_id}/plan", response_model=OperationIdResponse)
async def deployment_plan(
    deployment_id: uuid.UUID,
    body: DeploymentPlanBody,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_EDIT_ROLES),
) -> OperationIdResponse:
    """Run terraform plan with user-edited HCL against deployment's live state."""
    from app.api.routes.terraform import _run_plan_task

    deployment = await db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(status_code=404, detail="Deployment not found")

    _validate_hcl_binding(body.hcl, deployment)

    org_name = deployment.target_org
    operation_id = uuid.uuid4()

    active = await db.execute(
        select(Operation.id).where(
            Operation.deployment_id == deployment_id,
            Operation.status.in_(
                [OperationStatus.PENDING, OperationStatus.RUNNING]
            ),
        ).limit(1)
    )
    if active.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="Another operation is already running on this deployment",
        )

    locked = await acquire_org_lock(org_name, str(operation_id))
    if not locked:
        holder = await get_org_lock_holder(org_name)
        raise HTTPException(
            status_code=409,
            detail=f"Organisation '{org_name}' locked by operation {holder}",
        )

    try:
        workspace = TerraformWorkspace(org_name, operation_id)
        workspace.work_dir.mkdir(parents=True, exist_ok=True)
        attribution = Attribution(
            kc_username=user.username or "unknown",
            op_id=str(operation_id),
        )
        tagged_hcl = retag_hcl(body.hcl, attribution)
        (workspace.work_dir / "main.tf").write_text(tagged_hcl, encoding="utf-8")
        (workspace.work_dir / "provider.tf").write_text(
            _render_provider_tf(deployment_id), encoding="utf-8"
        )

        op = Operation(
            id=operation_id,
            type=OperationType.PLAN,
            status=OperationStatus.RUNNING,
            user_id=user.sub,
            username=user.username,
            target_org=org_name,
            deployment_id=deployment_id,
            target_edge_id=deployment.target_edge_id,
        )
        db.add(op)
        await db.commit()
    except Exception:
        await release_org_lock(org_name, str(operation_id))
        raise

    logger.info(
        "user=%s action=deployment_plan deployment=%s op=%s",
        user.username, deployment_id, operation_id,
    )

    asyncio.create_task(_run_plan_task(operation_id, org_name, workspace))
    return OperationIdResponse(operation_id=operation_id)


@router.post("/{deployment_id}/apply", response_model=OperationIdResponse)
async def deployment_apply(
    deployment_id: uuid.UUID,
    body: DeploymentApplyBody,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_EDIT_ROLES),
) -> OperationIdResponse:
    """Apply a previously successful plan for this deployment."""
    from app.api.routes.terraform import _run_apply_task

    deployment = await db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(status_code=404, detail="Deployment not found")

    plan_op = await db.get(Operation, body.operation_id)
    if plan_op is None:
        raise HTTPException(status_code=404, detail="Plan operation not found")
    if plan_op.deployment_id != deployment_id:
        raise HTTPException(
            status_code=400,
            detail="Plan operation does not belong to this deployment",
        )
    if plan_op.type != OperationType.PLAN:
        raise HTTPException(
            status_code=400, detail="Operation is not a plan"
        )
    if plan_op.status != OperationStatus.SUCCESS:
        raise HTTPException(
            status_code=400, detail="Can only apply a successful plan"
        )

    org_name = plan_op.target_org
    apply_id = uuid.uuid4()

    locked = await acquire_org_lock(org_name, str(apply_id))
    if not locked:
        holder = await get_org_lock_holder(org_name)
        raise HTTPException(
            status_code=409,
            detail=f"Organisation '{org_name}' locked by operation {holder}",
        )

    apply_op = Operation(
        id=apply_id,
        type=OperationType.APPLY,
        status=OperationStatus.RUNNING,
        user_id=user.sub,
        username=user.username,
        target_org=org_name,
        deployment_id=deployment_id,
        target_edge_id=deployment.target_edge_id,
    )
    db.add(apply_op)
    await db.commit()

    workspace = TerraformWorkspace(org_name, body.operation_id)

    logger.info(
        "user=%s action=deployment_apply deployment=%s plan_op=%s apply=%s",
        user.username, deployment_id, body.operation_id, apply_id,
    )

    asyncio.create_task(_run_apply_task(
        apply_id, org_name, workspace,
        deployment_id=deployment_id,
        version_source="apply",
        version_user=user.username,
    ))
    return OperationIdResponse(operation_id=apply_id)


class OrphanScanResponse(BaseModel):
    removed: list[str]
    kept: list[str]
    errors: list[str]


@router.get("/{deployment_id}/state/orphans", response_model=OrphanScanResponse)
async def scan_orphan_state(
    deployment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_EDIT_ROLES),  # noqa: ARG001
) -> OrphanScanResponse:
    """List state addresses that are not declared in the current HCL.

    Read-only: runs ``terraform state list`` and compares against
    addresses parsed from ``deployment.hcl``. Does not mutate state.
    Useful to preview what a cleanup would remove.
    """
    deployment = await db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(status_code=404, detail="Deployment not found")

    removed, kept, errors = await scan_and_remove_orphans(
        deployment.id,
        deployment.target_org,
        deployment.hcl or "",
        dry_run=True,
    )
    return OrphanScanResponse(removed=removed, kept=kept, errors=errors)


@router.post("/{deployment_id}/state/cleanup-orphans", response_model=OrphanScanResponse)
async def cleanup_orphan_state(
    deployment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_EDIT_ROLES),
) -> OrphanScanResponse:
    """Remove state entries whose address is not declared in the current HCL.

    ``terraform state rm`` only drops the state<->resource mapping; the
    real VCD resource is not touched. Safe to run when the same URN is
    tracked by a different address elsewhere in state (the common case
    for migration-era slugs that were already re-imported under the
    editor's naming scheme).

    Takes the org lock to avoid races with plan/apply.
    """
    deployment = await db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(status_code=404, detail="Deployment not found")

    org_name = deployment.target_org
    op_id = str(uuid.uuid4())
    locked = await acquire_org_lock(org_name, op_id)
    if not locked:
        holder = await get_org_lock_holder(org_name)
        raise HTTPException(
            status_code=409,
            detail=f"Organisation '{org_name}' locked by operation {holder}",
        )

    try:
        removed, kept, errors = await scan_and_remove_orphans(
            deployment.id,
            org_name,
            deployment.hcl or "",
            dry_run=False,
        )
    finally:
        await release_org_lock(org_name, op_id)

    logger.info(
        "user=%s action=cleanup_orphan_state deployment=%s removed=%d kept=%d errors=%d",
        user.username, deployment_id, len(removed), len(kept), len(errors),
    )
    return OrphanScanResponse(removed=removed, kept=kept, errors=errors)
