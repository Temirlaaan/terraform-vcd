"""CRUD endpoints for saved deployments."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthenticatedUser, require_roles
from app.database import get_db
from app.models.deployment import Deployment
from app.schemas.deployment import (
    DeploymentCreate,
    DeploymentList,
    DeploymentListItem,
    DeploymentOut,
    DeploymentUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deployments", tags=["deployments"])

_ANY_ROLE = require_roles("tf-admin", "tf-operator", "tf-viewer")


@router.post("", response_model=DeploymentOut, status_code=status.HTTP_201_CREATED)
async def create_deployment(
    body: DeploymentCreate,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_ANY_ROLE),
) -> DeploymentOut:
    """Persist a migration HCL generation as a named deployment.

    ``created_by`` is derived from the authenticated user, never from the
    request body.
    """
    # Build friendly description if user did not supply one:
    #   "<src_edge> -> <org>/<vdc>/<target_edge>  (manually saved)"
    default_desc = (
        f"{body.source_edge_name} -> "
        f"{body.target_org}/{body.target_vdc}/{body.target_edge_name or ''}  (manually saved)"
    )
    description = body.description if body.description else default_desc

    deployment = Deployment(
        name=body.name.strip(),
        description=description,
        source_host=body.source_host,
        source_edge_uuid=body.source_edge_uuid,
        source_edge_name=body.source_edge_name,
        verify_ssl=body.verify_ssl,
        target_org=body.target_org,
        target_vdc=body.target_vdc,
        target_vdc_id=body.target_vdc_id,
        target_edge_id=body.target_edge_id,
        target_edge_name=body.target_edge_name,
        hcl=body.hcl,
        summary=body.summary,
        created_by=user.username,
    )
    db.add(deployment)
    await db.commit()
    await db.refresh(deployment)

    logger.info(
        "user=%s action=deployment_create id=%s edge=%s",
        user.username, deployment.id, deployment.target_edge_id,
    )
    return DeploymentOut.model_validate(deployment)


@router.get("", response_model=DeploymentList)
async def list_deployments(
    target_edge_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_ANY_ROLE),  # noqa: ARG001
) -> DeploymentList:
    """List deployments, optionally filtered by ``target_edge_id``.

    Sorted by ``created_at DESC``.
    """
    stmt = select(Deployment)
    count_stmt = select(func.count()).select_from(Deployment)

    if target_edge_id:
        stmt = stmt.where(Deployment.target_edge_id == target_edge_id)
        count_stmt = count_stmt.where(Deployment.target_edge_id == target_edge_id)

    stmt = stmt.order_by(Deployment.created_at.desc()).limit(limit).offset(offset)

    items_result = await db.execute(stmt)
    total_result = await db.execute(count_stmt)

    items = items_result.scalars().all()
    total = total_result.scalar_one()

    return DeploymentList(
        items=[DeploymentListItem.model_validate(d) for d in items],
        total=total,
    )


@router.get("/{deployment_id}", response_model=DeploymentOut)
async def get_deployment(
    deployment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_ANY_ROLE),  # noqa: ARG001
) -> DeploymentOut:
    result = await db.execute(
        select(Deployment).where(Deployment.id == deployment_id)
    )
    deployment = result.scalar_one_or_none()
    if deployment is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return DeploymentOut.model_validate(deployment)


@router.patch("/{deployment_id}", response_model=DeploymentOut)
async def update_deployment(
    deployment_id: uuid.UUID,
    body: DeploymentUpdate,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_ANY_ROLE),
) -> DeploymentOut:
    result = await db.execute(
        select(Deployment).where(Deployment.id == deployment_id)
    )
    deployment = result.scalar_one_or_none()
    if deployment is None:
        raise HTTPException(status_code=404, detail="Deployment not found")

    if body.name is not None:
        deployment.name = body.name.strip()
    if body.description is not None:
        deployment.description = body.description

    await db.commit()
    await db.refresh(deployment)

    logger.info(
        "user=%s action=deployment_update id=%s",
        user.username, deployment.id,
    )
    return DeploymentOut.model_validate(deployment)


@router.delete("/{deployment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deployment(
    deployment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_ANY_ROLE),
) -> Response:
    result = await db.execute(
        select(Deployment).where(Deployment.id == deployment_id)
    )
    deployment = result.scalar_one_or_none()
    if deployment is None:
        raise HTTPException(status_code=404, detail="Deployment not found")

    await db.delete(deployment)
    await db.commit()

    logger.info(
        "user=%s action=deployment_delete id=%s",
        user.username, deployment_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
