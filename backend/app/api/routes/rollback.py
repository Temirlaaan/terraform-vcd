"""Phase 5 — whole-deployment rollback endpoints.

  POST /deployments/{id}/rollback/prepare        {version_num: N}
  POST /deployments/{id}/rollback/{op_id}/confirm

Prepare returns an operation_id; FE connects WebSocket to stream the
plan, then posts confirm to run apply.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import AuthenticatedUser, require_roles
from app.core import rollback as rollback_core

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deployments", tags=["rollback"])

_ADMIN_ONLY = require_roles("tf-admin")


class RollbackPrepareBody(BaseModel):
    version_num: int = Field(..., ge=1)


class RollbackOpResponse(BaseModel):
    operation_id: uuid.UUID


@router.post(
    "/{deployment_id}/rollback/prepare",
    response_model=RollbackOpResponse,
)
async def rollback_prepare(
    deployment_id: uuid.UUID,
    body: RollbackPrepareBody,
    user: AuthenticatedUser = Depends(_ADMIN_ONLY),
) -> RollbackOpResponse:
    logger.info(
        "user=%s action=rollback_prepare deployment=%s version_num=%d",
        user.username, deployment_id, body.version_num,
    )
    try:
        op_id = await rollback_core.prepare_rollback(
            deployment_id=deployment_id,
            version_num=body.version_num,
            user_sub=user.sub,
            username=user.username,
        )
    except rollback_core.RollbackError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return RollbackOpResponse(operation_id=op_id)


@router.post(
    "/{deployment_id}/rollback/{prepare_op_id}/confirm",
    response_model=RollbackOpResponse,
)
async def rollback_confirm(
    deployment_id: uuid.UUID,
    prepare_op_id: uuid.UUID,
    user: AuthenticatedUser = Depends(_ADMIN_ONLY),
) -> RollbackOpResponse:
    logger.info(
        "user=%s action=rollback_confirm deployment=%s prepare_op=%s",
        user.username, deployment_id, prepare_op_id,
    )
    try:
        apply_id = await rollback_core.confirm_rollback(
            prepare_op_id=prepare_op_id,
            user_sub=user.sub,
            username=user.username,
        )
    except rollback_core.RollbackError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    return RollbackOpResponse(operation_id=apply_id)
