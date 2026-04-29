"""Read-only + named-snapshot + pin toggle endpoints for deployment versions.

Workflow:
  * GET    /deployments/{id}/versions                 -> list all versions
  * GET    /deployments/{id}/versions/{n}/hcl         -> raw HCL
  * GET    /deployments/{id}/versions/{n}/state       -> raw tfstate JSON
  * POST   /deployments/{id}/versions/{n}/pin         -> is_pinned=true
  * POST   /deployments/{id}/versions/{n}/unpin       -> is_pinned=false (triggers rotation)
  * POST   /deployments/{id}/snapshots                -> pin latest as named snapshot
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthenticatedUser, require_roles
from app.core import minio_client, version_store
from app.database import get_db
from app.models.deployment import Deployment
from app.models.deployment_version import DeploymentVersion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deployments", tags=["versions"])

_ANY_ROLE = require_roles("tf-admin", "tf-operator", "tf-viewer")
_WRITE_ROLES = require_roles("tf-admin", "tf-operator")
_ADMIN_ONLY = require_roles("tf-admin")


class VersionItem(BaseModel):
    id: uuid.UUID
    version_num: int
    state_hash: str
    source: str
    label: str | None
    is_pinned: bool
    created_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


class VersionList(BaseModel):
    items: list[VersionItem]


class SnapshotCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=255)


async def _require_deployment(db: AsyncSession, deployment_id: uuid.UUID) -> Deployment:
    result = await db.execute(
        select(Deployment).where(Deployment.id == deployment_id)
    )
    dep = result.scalar_one_or_none()
    if dep is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return dep


async def _require_version(
    db: AsyncSession, deployment_id: uuid.UUID, version_num: int
) -> DeploymentVersion:
    result = await db.execute(
        select(DeploymentVersion).where(
            DeploymentVersion.deployment_id == deployment_id,
            DeploymentVersion.version_num == version_num,
        )
    )
    v = result.scalar_one_or_none()
    if v is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return v


@router.get("/{deployment_id}/versions", response_model=VersionList)
async def list_deployment_versions(
    deployment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_ANY_ROLE),  # noqa: ARG001
) -> VersionList:
    await _require_deployment(db, deployment_id)
    rows = await version_store.list_versions(db, deployment_id)
    return VersionList(items=[VersionItem.model_validate(r) for r in rows])


@router.get("/{deployment_id}/versions/{version_num}/hcl", response_class=PlainTextResponse)
async def get_version_hcl(
    deployment_id: uuid.UUID,
    version_num: int,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_WRITE_ROLES),  # noqa: ARG001
) -> PlainTextResponse:
    v = await _require_version(db, deployment_id, version_num)
    try:
        text = await minio_client.get_text(v.hcl_key)
    except Exception as exc:
        logger.error("get_version_hcl: cannot fetch %s: %s", v.hcl_key, exc)
        raise HTTPException(status_code=502, detail="Failed to load HCL from object store")
    return PlainTextResponse(text)


@router.get("/{deployment_id}/versions/{version_num}/state")
async def get_version_state(
    deployment_id: uuid.UUID,
    version_num: int,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_ADMIN_ONLY),  # noqa: ARG001
) -> Response:
    v = await _require_version(db, deployment_id, version_num)
    try:
        data = await minio_client.get_bytes(v.state_key)
    except Exception as exc:
        logger.error("get_version_state: cannot fetch %s: %s", v.state_key, exc)
        raise HTTPException(status_code=502, detail="Failed to load state from object store")
    return Response(content=data, media_type="application/json")


@router.post("/{deployment_id}/versions/{version_num}/pin", response_model=VersionItem)
async def pin_version(
    deployment_id: uuid.UUID,
    version_num: int,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_ADMIN_ONLY),
) -> VersionItem:
    await _require_deployment(db, deployment_id)
    try:
        row = await version_store.set_pinned(db, deployment_id, version_num, True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    logger.info(
        "user=%s action=pin deployment=%s v%d",
        user.username, deployment_id, version_num,
    )
    return VersionItem.model_validate(row)


@router.post("/{deployment_id}/versions/{version_num}/unpin", response_model=VersionItem)
async def unpin_version(
    deployment_id: uuid.UUID,
    version_num: int,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_ADMIN_ONLY),
) -> VersionItem:
    await _require_deployment(db, deployment_id)
    try:
        row = await version_store.set_pinned(db, deployment_id, version_num, False)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    logger.info(
        "user=%s action=unpin deployment=%s v%d",
        user.username, deployment_id, version_num,
    )
    return VersionItem.model_validate(row)


@router.post("/{deployment_id}/snapshots", response_model=VersionItem, status_code=201)
async def create_named_snapshot(
    deployment_id: uuid.UUID,
    body: SnapshotCreate,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_ADMIN_ONLY),
) -> VersionItem:
    await _require_deployment(db, deployment_id)
    try:
        row = await version_store.make_named_snapshot(
            db, deployment_id, body.label.strip(), user.username
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    logger.info(
        "user=%s action=named_snapshot deployment=%s v%d label=%s",
        user.username, deployment_id, row.version_num, row.label,
    )
    return VersionItem.model_validate(row)
