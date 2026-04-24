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
from app.core import minio_client, version_store
from app.core.locking import acquire_org_lock, release_org_lock, get_org_lock_holder
from app.core.tf_workspace import TerraformWorkspace
from app.database import get_db
from app.models.deployment import Deployment
from app.models.deployment_version import DeploymentVersion
from app.models.operation import Operation, OperationStatus, OperationType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deployments", tags=["deployment-hcl"])

_EDIT_ROLES = require_roles("tf-admin", "tf-operator")
_READ_ROLES = require_roles("tf-admin", "tf-operator", "tf-viewer")


class DeploymentPlanBody(BaseModel):
    hcl: str


class DeploymentApplyBody(BaseModel):
    operation_id: uuid.UUID


class OperationIdResponse(BaseModel):
    operation_id: uuid.UUID


def _render_provider_tf(deployment_id: uuid.UUID) -> str:
    from jinja2 import Environment, FileSystemLoader

    tpl_dir = (
        Path(__file__).resolve().parent.parent.parent / "templates" / "migration"
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
    """Return latest version's main.tf as plaintext."""
    deployment = await db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(status_code=404, detail="Deployment not found")

    res = await db.execute(
        select(DeploymentVersion)
        .where(DeploymentVersion.deployment_id == deployment_id)
        .order_by(desc(DeploymentVersion.version_num))
        .limit(1)
    )
    latest = res.scalar_one_or_none()
    if latest is None:
        raise HTTPException(
            status_code=404,
            detail="No version snapshot exists for this deployment yet",
        )

    try:
        hcl = await minio_client.get_text(latest.hcl_key)
    except Exception as exc:
        logger.exception("Failed to read HCL for deployment %s", deployment_id)
        raise HTTPException(
            status_code=410,
            detail=f"HCL blob missing in MinIO: {exc}",
        )
    return hcl


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
        (workspace.work_dir / "main.tf").write_text(body.hcl, encoding="utf-8")
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
