"""Version snapshot/rotation/restore for deployments.

Layout in MinIO bucket ``terraform-state``::

    deployments/<deployment_id>/current/terraform.tfstate   (live state, written by TF backend)
    deployments/<deployment_id>/v<N>/main.tf
    deployments/<deployment_id>/v<N>/terraform.tfstate

Rules:
  * Dedup: skip insert if ``state_hash`` matches the latest version
    (rollback/force_new bypasses via timestamp suffix).
  * Rotation: keep at most ``MAX_NON_PINNED`` non-pinned versions per
    deployment; older non-pinned versions and their MinIO objects are
    deleted. MinIO deletion errors are logged but do not abort the batch.
  * Pinned versions never rotate. Auto-pinned sources:
      - migration_baseline  (migration flow, explicit is_pinned)
      - named_snapshot      (make_named_snapshot)
      - initial_baseline    (very first v1 of any deployment)
    Rollback rows are NOT auto-pinned; admins pin manually via
    ``set_pinned`` if the rollback state should survive rotation.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core import minio_client
from app.core.state_hash import compute_state_hash
from app.models.deployment_version import DeploymentVersion

logger = logging.getLogger(__name__)


MAX_NON_PINNED = 7


def state_key_for_deployment(deployment_id: uuid.UUID) -> str:
    """Live (working) state key used by terraform's S3 backend."""
    return f"deployments/{deployment_id}/current/terraform.tfstate"


def _version_prefix(deployment_id: uuid.UUID, version_num: int) -> str:
    return f"deployments/{deployment_id}/v{version_num}"


def _hcl_key(deployment_id: uuid.UUID, version_num: int) -> str:
    return f"{_version_prefix(deployment_id, version_num)}/main.tf"


def _state_snapshot_key(deployment_id: uuid.UUID, version_num: int) -> str:
    return f"{_version_prefix(deployment_id, version_num)}/terraform.tfstate"


async def snapshot_version(
    db: AsyncSession,
    deployment_id: uuid.UUID,
    workspace_dir: Path,
    source: str,
    created_by: str,
    label: str | None = None,
    is_pinned: bool = False,
    force_new: bool = False,
) -> DeploymentVersion | None:
    """Snapshot ``main.tf`` + ``terraform.tfstate`` from ``workspace_dir``.

    Returns the new ``DeploymentVersion`` row, or ``None`` if dedup skipped it.

    Caller must already have committed the workspace state (i.e. apply or
    refresh-only succeeded). Uses ``terraform show -json`` to compute a
    canonical state hash for dedup.

    Auto-pin rule applied before insert:
      * first version (``version_num == 1``) of a deployment is pinned as
        ``initial_baseline`` (unless caller already set is_pinned or
        supplied a label). Oldest restorable point must survive rotation.
    """
    state_hash = await compute_state_hash(workspace_dir, settings.terraform_binary)

    last = await db.execute(
        select(DeploymentVersion)
        .where(DeploymentVersion.deployment_id == deployment_id)
        .order_by(DeploymentVersion.version_num.desc())
        .limit(1)
    )
    last_row = last.scalar_one_or_none()
    if force_new:
        # Rollback / forced snapshot: always record an event, even when
        # restored state matches an existing (not just latest) version.
        # UNIQUE(deployment_id, state_hash) spans ALL rows — must suffix
        # unconditionally to dodge collisions with older versions.
        import time as _time
        state_hash = f"{state_hash}:{source}:{int(_time.time()*1000)}"
        logger.info(
            "snapshot force_new: deployment=%s suffixed hash (source=%s)",
            deployment_id, source,
        )
    elif last_row is not None and last_row.state_hash == state_hash:
        logger.info(
            "snapshot dedup: deployment=%s state_hash matches v%d, skipping",
            deployment_id, last_row.version_num,
        )
        return None

    next_num = (last_row.version_num + 1) if last_row else 1

    # Auto-pin baseline: the very first version of a deployment must
    # survive rotation — it is the oldest restorable point.
    if next_num == 1 and not is_pinned:
        is_pinned = True
        if label is None:
            label = "initial_baseline"
        logger.info(
            "snapshot: auto-pin first version as baseline deployment=%s",
            deployment_id,
        )

    hcl_key = _hcl_key(deployment_id, next_num)
    state_key = _state_snapshot_key(deployment_id, next_num)

    main_tf = workspace_dir / "main.tf"
    state_file = workspace_dir / "terraform.tfstate"
    hcl_text = main_tf.read_text(encoding="utf-8") if main_tf.exists() else ""
    state_bytes = state_file.read_bytes() if state_file.exists() else b""

    # If terraform's backend is S3 (it is, per Phase 1) the local file may
    # be absent — pull it from the live state key in MinIO instead.
    if not state_bytes:
        try:
            state_bytes = await minio_client.get_bytes(state_key_for_deployment(deployment_id))
        except Exception as exc:
            logger.warning(
                "snapshot: cannot read live state for deployment=%s: %s",
                deployment_id, exc,
            )
            state_bytes = b""

    await minio_client.put_text(hcl_key, hcl_text, content_type="text/plain")
    await minio_client.put_bytes(state_key, state_bytes, content_type="application/json")

    row = DeploymentVersion(
        id=uuid.uuid4(),
        deployment_id=deployment_id,
        version_num=next_num,
        state_hash=state_hash,
        hcl_key=hcl_key,
        state_key=state_key,
        source=source,
        label=label,
        is_pinned=is_pinned,
        created_by=created_by,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # UNIQUE(deployment_id, state_hash) was hit by a non-latest row
        # (latest was already ruled out by the earlier dedup check). This
        # means the apply rewound state to a shape that a prior version
        # already has — e.g. destroy of just-added resources returns
        # state to v(N-k) hash. Still want the event in history, so retry
        # with a suffixed hash (same trick as force_new).
        import time as _time
        row.state_hash = f"{state_hash}:{source}:{int(_time.time()*1000)}"
        db.add(row)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            logger.info(
                "snapshot dedup race: deployment=%s state_hash collision after suffix, skipping",
                deployment_id,
            )
            return None
        logger.info(
            "snapshot: state_hash collided with prior version, inserted v%d with suffixed hash deployment=%s",
            next_num, deployment_id,
        )

    await db.refresh(row)
    logger.info(
        "snapshot stored: deployment=%s v%d source=%s pinned=%s",
        deployment_id, next_num, source, is_pinned,
    )

    if not is_pinned:
        await rotate(db, deployment_id)

    return row


async def rotate(db: AsyncSession, deployment_id: uuid.UUID) -> int:
    """Delete oldest non-pinned versions beyond ``MAX_NON_PINNED``.

    MinIO deletion errors are logged and swallowed — a failure there must
    not abort the batch nor leave a DB row pointing at a ghost blob
    indefinitely. If MinIO is truly down, the next rotation pass will
    retry (rows still exist with the same keys).

    Returns count of DB rows deleted.
    """
    result = await db.execute(
        select(DeploymentVersion)
        .where(
            DeploymentVersion.deployment_id == deployment_id,
            DeploymentVersion.is_pinned.is_(False),
        )
        .order_by(DeploymentVersion.version_num.desc())
    )
    non_pinned = list(result.scalars().all())
    to_delete = non_pinned[MAX_NON_PINNED:]
    if not to_delete:
        return 0

    deleted = 0
    for row in to_delete:
        for key in (row.hcl_key, row.state_key):
            try:
                await minio_client.delete_key(key)
            except Exception as exc:
                logger.warning(
                    "rotation: MinIO delete failed key=%s deployment=%s v%d: %s",
                    key, deployment_id, row.version_num, exc,
                )
        await db.delete(row)
        deleted += 1

    await db.commit()
    logger.info(
        "rotation: deployment=%s deleted %d old non-pinned versions",
        deployment_id, deleted,
    )
    return deleted


async def restore(
    db: AsyncSession,
    deployment_id: uuid.UUID,
    version_num: int,
    created_by: str,
) -> DeploymentVersion | None:
    """Legacy stub — rollback lives in ``app/core/rollback.py``.

    Phase 5 implements rollback as a prepare/confirm flow rather than a
    single restore call, so this entry point is retained only for
    backwards compatibility and raises ``NotImplementedError``.
    """
    raise NotImplementedError(
        "Use app.core.rollback.prepare_rollback / confirm_rollback"
    )


async def latest_version(
    db: AsyncSession, deployment_id: uuid.UUID
) -> DeploymentVersion | None:
    result = await db.execute(
        select(DeploymentVersion)
        .where(DeploymentVersion.deployment_id == deployment_id)
        .order_by(DeploymentVersion.version_num.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_versions(
    db: AsyncSession, deployment_id: uuid.UUID
) -> list[DeploymentVersion]:
    result = await db.execute(
        select(DeploymentVersion)
        .where(DeploymentVersion.deployment_id == deployment_id)
        .order_by(DeploymentVersion.version_num.desc())
    )
    return list(result.scalars().all())


async def count_versions(db: AsyncSession, deployment_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(DeploymentVersion)
        .where(DeploymentVersion.deployment_id == deployment_id)
    )
    return int(result.scalar_one())


async def set_pinned(
    db: AsyncSession,
    deployment_id: uuid.UUID,
    version_num: int,
    pinned: bool,
) -> DeploymentVersion:
    """Toggle ``is_pinned`` on a version.

    When unpinning, a rotation pass runs after commit so the newly
    non-pinned row is considered for removal if the deployment is over
    ``MAX_NON_PINNED``.
    """
    result = await db.execute(
        select(DeploymentVersion).where(
            DeploymentVersion.deployment_id == deployment_id,
            DeploymentVersion.version_num == version_num,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ValueError(f"Version v{version_num} not found")

    if row.is_pinned == pinned:
        return row

    row.is_pinned = pinned
    await db.commit()
    await db.refresh(row)
    logger.info(
        "set_pinned: deployment=%s v%d pinned=%s",
        deployment_id, version_num, pinned,
    )

    if not pinned:
        await rotate(db, deployment_id)

    return row


async def make_named_snapshot(
    db: AsyncSession,
    deployment_id: uuid.UUID,
    label: str,
    created_by: str,
) -> DeploymentVersion:
    """Pin the latest version (or copy it as a new pinned version).

    Spec: takes current v<N>, copies as new version with is_pinned=TRUE,
    source='named_snapshot', label=<given>. We copy MinIO objects to a
    fresh v<N+1> prefix so deletion of the original (rotation) does not
    orphan the snapshot.
    """
    last = await latest_version(db, deployment_id)
    if last is None:
        raise ValueError("Cannot snapshot: deployment has no versions yet")

    next_num = last.version_num + 1
    new_hcl_key = _hcl_key(deployment_id, next_num)
    new_state_key = _state_snapshot_key(deployment_id, next_num)

    await minio_client.copy_key(last.hcl_key, new_hcl_key)
    await minio_client.copy_key(last.state_key, new_state_key)

    row = DeploymentVersion(
        id=uuid.uuid4(),
        deployment_id=deployment_id,
        version_num=next_num,
        state_hash=last.state_hash + ":named",  # avoid UNIQUE collision with source v
        hcl_key=new_hcl_key,
        state_key=new_state_key,
        source="named_snapshot",
        label=label,
        is_pinned=True,
        created_by=created_by,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row
