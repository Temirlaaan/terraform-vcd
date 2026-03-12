import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthenticatedUser, require_roles
from app.core.hcl_generator import HCLGenerator
from app.core.locking import acquire_org_lock, get_org_lock_holder, release_org_lock
from app.core.tf_runner import TerraformRunner
from app.core.tf_workspace import TerraformWorkspace
from app.database import get_db
from app.models.operation import Operation, OperationStatus, OperationType
from app.schemas.terraform import (
    TerraformApplyRequest,
    TerraformGenerateRequest,
    TerraformGenerateResponse,
    TerraformPlanRequest,
    TerraformPlanResponse,
)
from sqlalchemy import select

router = APIRouter(prefix="/terraform", tags=["terraform"])

_generator = HCLGenerator()


@router.post("/generate", response_model=TerraformGenerateResponse)
async def generate_hcl(
    body: TerraformGenerateRequest,
    user: AuthenticatedUser = Depends(require_roles("tf-admin", "tf-operator", "tf-viewer")),
):
    """Accept a full form-state config and return rendered HCL."""
    try:
        hcl = _generator.generate(body.config)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return TerraformGenerateResponse(hcl=hcl)


def _extract_org_name(config: dict) -> str:
    """Pull the target organisation name from the config payload."""
    org = config.get("org")
    if not org or not org.get("name"):
        raise HTTPException(
            status_code=422,
            detail="config.org.name is required",
        )
    return org["name"]


@router.post("/plan", response_model=TerraformPlanResponse)
async def plan(
    body: TerraformPlanRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(require_roles("tf-admin", "tf-operator")),
):
    """Generate HCL, run ``terraform init`` + ``terraform plan``.

    Returns the ``operation_id`` immediately after the plan completes.
    A Redis lock prevents concurrent operations on the same Org.
    """
    org_name = _extract_org_name(body.config)
    operation_id = uuid.uuid4()

    # --- Acquire distributed lock ---
    locked = await acquire_org_lock(org_name, str(operation_id))
    if not locked:
        holder = await get_org_lock_holder(org_name)
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

    workspace = TerraformWorkspace(org_name, operation_id)
    try:
        # --- Write HCL to workspace ---
        workspace.create(body.config)

        # --- terraform init ---
        runner = TerraformRunner(workspace.work_dir, operation_id=str(operation_id))
        init_result = await runner.init()
        if not init_result.success:
            operation.status = OperationStatus.FAILED
            operation.error_message = init_result.stderr
            operation.completed_at = datetime.now(timezone.utc)
            await db.commit()
            raise HTTPException(status_code=500, detail=init_result.stderr)

        # --- terraform plan ---
        plan_result = await runner.plan()
        operation.plan_output = plan_result.stdout
        if plan_result.success:
            operation.status = OperationStatus.SUCCESS
        else:
            operation.status = OperationStatus.FAILED
            operation.error_message = plan_result.stderr
        operation.completed_at = datetime.now(timezone.utc)
        await db.commit()

        if not plan_result.success:
            raise HTTPException(status_code=500, detail=plan_result.stderr)

        return TerraformPlanResponse(operation_id=operation_id)

    except HTTPException:
        raise
    except Exception as exc:
        operation.status = OperationStatus.FAILED
        operation.error_message = str(exc)
        operation.completed_at = datetime.now(timezone.utc)
        await db.commit()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        await release_org_lock(org_name, str(operation_id))


@router.post("/apply", response_model=TerraformPlanResponse)
async def apply(
    body: TerraformApplyRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(require_roles("tf-admin", "tf-operator")),
):
    """Execute ``terraform apply`` for a previously successful plan.

    Looks up the plan operation by ID, finds its workspace, acquires
    an org lock, then runs ``terraform apply plan.bin``.
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

    # --- Acquire distributed lock ---
    locked = await acquire_org_lock(org_name, str(apply_id))
    if not locked:
        holder = await get_org_lock_holder(org_name)
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
    try:
        runner = TerraformRunner(workspace.work_dir, operation_id=str(apply_id))
        apply_result = await runner.apply()

        operation.plan_output = apply_result.stdout
        if apply_result.success:
            operation.status = OperationStatus.SUCCESS
        else:
            operation.status = OperationStatus.FAILED
            operation.error_message = apply_result.stderr
        operation.completed_at = datetime.now(timezone.utc)
        await db.commit()

        if not apply_result.success:
            raise HTTPException(status_code=500, detail=apply_result.stderr)

        return TerraformPlanResponse(operation_id=apply_id)

    except HTTPException:
        raise
    except Exception as exc:
        operation.status = OperationStatus.FAILED
        operation.error_message = str(exc)
        operation.completed_at = datetime.now(timezone.utc)
        await db.commit()
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        await release_org_lock(org_name, str(apply_id))
