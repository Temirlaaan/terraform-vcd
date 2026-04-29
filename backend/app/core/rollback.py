"""Phase 5: whole-deployment rollback helpers.

Two-step flow so admin sees plan diff before destructive apply:

  1. ``prepare_rollback`` — copy v<N> HCL into live workspace (state untouched —
     terraform diffs real VCD against v<N> HCL), run ``terraform init`` and ``terraform plan`` (refresh ON — we need
     to see real VCD diff vs target HCL). Update op row with plan output. Original live state is backed up
     under ``deployments/<id>/pre-rollback/terraform.tfstate`` (single-slot,
     overwritten on each new prepare).

  2. ``apply_rollback`` — admin confirms, we launch apply on the same
     workspace (plan.bin still present), and snapshot result as a new
     non-pinned version with ``source='rollback'``, ``label='rollback-to-v<N>'``.

Safety rails:
  * Reject if any ``drift_reports`` for the deployment has ``resolution IS NULL``
    and ``has_changes=true`` (unreviewed drift).
  * Reject if any non-terminal operation exists for the deployment
    (``status IN (PENDING, RUNNING)``).
  * 404 if version row absent. 410 if version row present but MinIO blob gone.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core import minio_client
from app.core.aria_attribution import Attribution, retag_hcl
from app.core import version_store
from app.core.locking import acquire_org_lock, release_org_lock
from app.core.tf_runner import TerraformRunner, log_channel
from app.core.tf_workspace import TerraformWorkspace
from app.database import async_session
from app.models.deployment import Deployment
from app.models.deployment_version import DeploymentVersion
from app.models.drift_report import DriftReport
from app.models.operation import Operation, OperationStatus, OperationType

logger = logging.getLogger(__name__)


def _pre_rollback_backup_key(deployment_id: uuid.UUID) -> str:
    return f"deployments/{deployment_id}/pre-rollback/terraform.tfstate"


class RollbackError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


async def _check_unreviewed_drift(
    db: AsyncSession, deployment_id: uuid.UUID
) -> list[uuid.UUID]:
    result = await db.execute(
        select(DriftReport.id).where(
            DriftReport.deployment_id == deployment_id,
            DriftReport.has_changes.is_(True),
            DriftReport.resolution.is_(None),
        )
    )
    return [r for (r,) in result.all()]


async def _check_active_operation(
    db: AsyncSession, deployment_id: uuid.UUID
) -> uuid.UUID | None:
    result = await db.execute(
        select(Operation.id).where(
            Operation.deployment_id == deployment_id,
            Operation.status.in_([OperationStatus.PENDING, OperationStatus.RUNNING]),
        ).limit(1)
    )
    return result.scalar_one_or_none()


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


async def prepare_rollback(
    deployment_id: uuid.UUID,
    version_num: int,
    user_sub: str,
    username: str,
) -> uuid.UUID:
    """Validate + copy target version into live, run plan. Returns operation_id.

    Launches plan as background task; caller polls Operation row / WS.
    """
    async with async_session() as db:
        deployment = await db.get(Deployment, deployment_id)
        if deployment is None:
            raise RollbackError(404, "Deployment not found")

        result = await db.execute(
            select(DeploymentVersion).where(
                DeploymentVersion.deployment_id == deployment_id,
                DeploymentVersion.version_num == version_num,
            )
        )
        version = result.scalar_one_or_none()
        if version is None:
            raise RollbackError(404, f"Version v{version_num} not found")

        # Blob existence check (rotation may have deleted it separately)
        hcl_exists = await minio_client.exists(version.hcl_key)
        state_exists = await minio_client.exists(version.state_key)
        if not (hcl_exists and state_exists):
            raise RollbackError(
                410,
                f"Version v{version_num} has been rotated out — MinIO objects missing",
            )

        unreviewed = await _check_unreviewed_drift(db, deployment_id)
        if unreviewed:
            raise RollbackError(
                409,
                "Rollback blocked: unreviewed drift reports exist. "
                f"Resolve drift first via POST /drift-reports/<id>/review. "
                f"Pending report ids: {[str(x) for x in unreviewed]}",
            )

        active = await _check_active_operation(db, deployment_id)
        if active:
            raise RollbackError(
                409,
                f"Rollback blocked: operation {active} already running on deployment",
            )

        org_name = deployment.target_org
        operation_id = uuid.uuid4()

        locked = await acquire_org_lock(org_name, str(operation_id))
        if not locked:
            raise RollbackError(
                409, f"Organisation '{org_name}' locked by concurrent operation"
            )

        try:
            # 1. Backup current live state to pre-rollback/ (overwrite previous)
            live_key = version_store.state_key_for_deployment(deployment_id)
            try:
                await minio_client.copy_key(
                    live_key, _pre_rollback_backup_key(deployment_id)
                )
                logger.info(
                    "pre-rollback backup: deployment=%s -> %s",
                    deployment_id, _pre_rollback_backup_key(deployment_id),
                )
            except Exception as exc:
                logger.warning(
                    "pre-rollback backup failed (continuing): %s", exc
                )

            # 2. Keep live state as-is. Apply v<N> HCL against current state
            #    so terraform native diff removes/adds resources to reach v<N>.
            #    (state-copy approach produced no-op plan when reality had
            #     diverged — see STATUS.md Phase 5 notes.)

            # 3. Build workspace with v<N> HCL + provider pointing to live key
            workspace = TerraformWorkspace(org_name, operation_id)
            workspace.work_dir.mkdir(parents=True, exist_ok=True)
            hcl_text = await minio_client.get_text(version.hcl_key)
            # Phase 8: retag descriptions with current admin so the rollback
            # apply emits VCD events attributed to the operator who confirmed
            # it, not the admin who created the snapshot.
            attribution = Attribution(
                kc_username=username or "unknown",
                op_id=str(operation_id),
            )
            (workspace.work_dir / "main.tf").write_text(
                retag_hcl(hcl_text, attribution), encoding="utf-8"
            )
            (workspace.work_dir / "provider.tf").write_text(
                _render_provider_tf(deployment_id), encoding="utf-8"
            )

            # 4. Create ROLLBACK op row (PLAN phase of rollback)
            op = Operation(
                id=operation_id,
                type=OperationType.ROLLBACK,
                status=OperationStatus.RUNNING,
                user_id=user_sub,
                username=username,
                target_org=org_name,
                deployment_id=deployment_id,
                target_edge_id=deployment.target_edge_id,
                rollback_from_version=version_num,
            )
            db.add(op)
            await db.commit()
        except Exception:
            await release_org_lock(org_name, str(operation_id))
            raise

    # 5. Launch background plan
    asyncio.create_task(
        _run_rollback_plan_task(operation_id, org_name, workspace)
    )
    return operation_id


async def _run_rollback_plan_task(
    operation_id: uuid.UUID,
    org_name: str,
    workspace: TerraformWorkspace,
) -> None:
    from redis.asyncio import Redis
    redis: Redis | None = None
    try:
        if operation_id:
            redis = Redis.from_url(settings.redis_url, decode_responses=True)
            ch = log_channel(str(operation_id))
            await redis.publish(
                ch, "[stdout] [rollback:prepare] terraform init"
            )

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
                if redis:
                    await redis.publish(ch, "__EXIT:1")
                return

            if redis:
                await redis.publish(
                    ch, "[stdout] [rollback:prepare] terraform plan"
                )

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
        logger.exception("_run_rollback_plan_task failed for %s", operation_id)
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
        if redis:
            try:
                await redis.publish(log_channel(str(operation_id)), "__EXIT:1")
            except Exception:
                pass
    finally:
        if redis:
            try:
                await redis.aclose()
            except Exception:
                pass
        await release_org_lock(org_name, str(operation_id))


async def confirm_rollback(
    prepare_op_id: uuid.UUID,
    user_sub: str,
    username: str,
) -> uuid.UUID:
    """Launch apply on a successful rollback prepare op. Returns apply_id."""
    from app.api.routes.terraform import _run_apply_task

    async with async_session() as db:
        prepare_op = await db.get(Operation, prepare_op_id)
        if prepare_op is None:
            raise RollbackError(404, "Prepare operation not found")
        if prepare_op.type != OperationType.ROLLBACK:
            raise RollbackError(400, "Operation is not a rollback prepare")
        if prepare_op.status != OperationStatus.SUCCESS:
            raise RollbackError(400, "Can only confirm a successful rollback plan")
        if prepare_op.rollback_from_version is None:
            raise RollbackError(500, "Prepare op missing rollback_from_version")
        if prepare_op.deployment_id is None:
            raise RollbackError(500, "Prepare op missing deployment_id")

        deployment_id = prepare_op.deployment_id
        version_num = prepare_op.rollback_from_version
        org_name = prepare_op.target_org

        # Re-check safety rails (drift may have arrived between prepare and confirm)
        unreviewed = await _check_unreviewed_drift(db, deployment_id)
        if unreviewed:
            raise RollbackError(
                409,
                "Rollback blocked at confirm: new unreviewed drift reports "
                f"since prepare. Pending: {[str(x) for x in unreviewed]}",
            )

        apply_id = uuid.uuid4()
        locked = await acquire_org_lock(org_name, str(apply_id))
        if not locked:
            raise RollbackError(
                409, f"Organisation '{org_name}' locked by concurrent operation"
            )

        apply_op = Operation(
            id=apply_id,
            type=OperationType.ROLLBACK,
            status=OperationStatus.RUNNING,
            user_id=user_sub,
            username=username,
            target_org=org_name,
            deployment_id=deployment_id,
            target_edge_id=prepare_op.target_edge_id,
            rollback_from_version=version_num,
        )
        db.add(apply_op)
        await db.commit()

    # Reuse prepare workspace (has plan.bin)
    workspace = TerraformWorkspace(org_name, prepare_op_id)

    asyncio.create_task(_run_apply_task(
        apply_id, org_name, workspace,
        deployment_id=deployment_id,
        version_source="rollback",
        version_user=username,
        version_label=f"rollback-to-v{version_num}",
        version_pinned=False,
    ))
    return apply_id
