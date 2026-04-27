"""CRUD endpoints for saved deployments."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator

from app.auth import AuthenticatedUser, require_roles
from app.core import minio_client
from app.core.deployment_builder import build_hcl, summary_from_spec
from app.core.deployment_spec_from_state import parse_state_text
from app.core.deployment_state_align import align_state_to_hcl
from app.database import get_db
from app.models.deployment import Deployment
from app.schemas.deployment import (
    DeploymentCreate,
    DeploymentList,
    DeploymentListItem,
    DeploymentOut,
    DeploymentUpdate,
)
from app.schemas.deployment_spec import DeploymentSpec, EditorData, TargetSpec
from app.schemas.terraform import _validate_safe_name

import json


def _spec_key(deployment_id: uuid.UUID) -> str:
    """MinIO key for the last saved rule spec of a deployment.

    Written on every ``POST /manual`` and ``PUT /spec`` so subsequent
    editor opens can re-hydrate the edited spec without needing a
    Terraform apply first. Falls back to state parsing if absent (legacy
    deployments created before the editor existed).
    """
    return f"deployments/{deployment_id}/current/spec.json"


async def _persist_spec(deployment_id: uuid.UUID, spec: DeploymentSpec) -> None:
    await minio_client.put_text(
        _spec_key(deployment_id),
        json.dumps(spec.model_dump(), ensure_ascii=False),
        content_type="application/json",
    )


class DeploymentManualCreate(BaseModel):
    """Body for ``POST /deployments/manual``.

    ``target`` and ``spec.target`` must match — we persist the target
    from the top level; spec carries its own copy so a freshly-parsed
    EditorData payload can be round-tripped unchanged.
    """

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    spec: DeploymentSpec

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_safe_name(v, "name")


class DeploymentSpecUpdate(BaseModel):
    """Body for ``PUT /deployments/{id}/spec``."""

    spec: DeploymentSpec

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


_WRITE_ROLE = require_roles("tf-admin", "tf-operator")


@router.post(
    "/manual",
    response_model=DeploymentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_manual_deployment(
    body: DeploymentManualCreate,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_WRITE_ROLE),
) -> DeploymentOut:
    """Create a greenfield (non-migration) deployment from a rule spec.

    The spec is rendered to HCL here, so the saved deployment row is
    immediately usable by the existing Plan/Apply flow — no separate
    "save" step required. ``kind`` is forced to ``manual`` regardless
    of what the client sends.
    """
    hcl = build_hcl(body.spec)
    summary = summary_from_spec(body.spec)
    target = body.spec.target

    default_desc = (
        f"Manual deployment -> {target.org}/{target.vdc}"
        f"/{target.edge_name or target.edge_id}"
    )
    description = body.description or default_desc

    deployment = Deployment(
        name=body.name.strip(),
        kind="manual",
        description=description,
        source_host="",
        source_edge_uuid="",
        source_edge_name="",
        verify_ssl=False,
        target_org=target.org,
        target_vdc=target.vdc,
        target_vdc_id=target.vdc_id,
        target_edge_id=target.edge_id,
        target_edge_name=target.edge_name,
        hcl=hcl,
        summary=summary,
        created_by=user.username,
    )
    db.add(deployment)
    await db.commit()
    await db.refresh(deployment)

    await _persist_spec(deployment.id, body.spec)

    logger.info(
        "user=%s action=deployment_manual_create id=%s name=%s edge=%s",
        user.username, deployment.id, deployment.name, target.edge_id,
    )
    return DeploymentOut.model_validate(deployment)


@router.put("/{deployment_id}/spec", response_model=DeploymentOut)
async def update_deployment_spec(
    deployment_id: uuid.UUID,
    body: DeploymentSpecUpdate,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_WRITE_ROLE),
) -> DeploymentOut:
    """Rewrite a deployment's HCL from a new rule spec.

    Applies to both ``manual`` and ``migration`` deployments — the edit
    form is the single source of truth for the stored HCL. The caller
    must run Plan + Apply afterwards to reconcile VCD with the new
    config; no implicit apply happens here.

    The spec's ``target`` is validated against the deployment's
    persisted target; changing target on an existing deployment is
    rejected (use Create + delete old).
    """
    result = await db.execute(
        select(Deployment).where(Deployment.id == deployment_id)
    )
    deployment = result.scalar_one_or_none()
    if deployment is None:
        raise HTTPException(status_code=404, detail="Deployment not found")

    spec_target = body.spec.target
    target_changed = spec_target.edge_id != deployment.target_edge_id
    if target_changed:
        # Allowed but risky: usually means an edge was recreated in VCD
        # under a fresh URN while keeping the same name, so the caller
        # re-pointed the deployment. Log loudly and update the DB row.
        # State align runs afterwards against the new edge key, so any
        # resource whose edge_gateway_id is tied to the old URN will
        # surface as destroy+create on the next Plan (expected).
        logger.warning(
            "user=%s action=deployment_spec_target_change id=%s old=%s new=%s",
            user.username,
            deployment.id,
            deployment.target_edge_id,
            spec_target.edge_id,
        )

    old_hcl = deployment.hcl or ""
    hcl = build_hcl(body.spec)
    deployment.hcl = hcl
    deployment.summary = summary_from_spec(body.spec)
    # target_vdc_id may have been empty on migration rows — backfill on edit.
    if spec_target.vdc_id and not deployment.target_vdc_id:
        deployment.target_vdc_id = spec_target.vdc_id
    if spec_target.edge_name and not deployment.target_edge_name:
        deployment.target_edge_name = spec_target.edge_name
    if target_changed:
        deployment.target_edge_id = spec_target.edge_id
        if spec_target.edge_name:
            deployment.target_edge_name = spec_target.edge_name
        if spec_target.vdc_id:
            deployment.target_vdc_id = spec_target.vdc_id
        if spec_target.org:
            deployment.target_org = spec_target.org
        if spec_target.vdc:
            deployment.target_vdc = spec_target.vdc
    deployment.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(deployment)

    await _persist_spec(deployment.id, body.spec)

    # Align Terraform state addresses to the new HCL so the next plan
    # does not show destroy+create for resources whose slug changed
    # (e.g. migration-style ``tcp_53`` -> editor-style ``ttc_fw_tcp_53``).
    # Best-effort: init + state mv; failures logged but do not fail save.
    if old_hcl.strip() and old_hcl != hcl:
        try:
            applied, errors = await align_state_to_hcl(
                deployment.id, deployment.target_org, old_hcl, hcl
            )
            if applied:
                logger.info(
                    "state-align: deployment=%s applied=%d moves=%s",
                    deployment.id, len(applied), applied,
                )
            for err in errors:
                logger.warning("state-align: deployment=%s %s", deployment.id, err)
        except Exception:
            logger.exception(
                "state-align: unexpected failure deployment=%s", deployment.id
            )

    logger.info(
        "user=%s action=deployment_spec_update id=%s",
        user.username, deployment.id,
    )
    return DeploymentOut.model_validate(deployment)


@router.get("/{deployment_id}/editor-data", response_model=EditorData)
async def get_deployment_editor_data(
    deployment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_ANY_ROLE),  # noqa: ARG001
) -> EditorData:
    """Return the editable rule-spec for an existing deployment.

    Source of truth is the latest state in MinIO
    (``deployments/<id>/current/terraform.tfstate``). When state is not
    present yet — e.g. a freshly created manual deployment that has
    never been applied — returns an empty spec carrying just the target.
    """
    result = await db.execute(
        select(Deployment).where(Deployment.id == deployment_id)
    )
    deployment = result.scalar_one_or_none()
    if deployment is None:
        raise HTTPException(status_code=404, detail="Deployment not found")

    target = TargetSpec(
        org=deployment.target_org or "",
        vdc=deployment.target_vdc or "",
        vdc_id=deployment.target_vdc_id or "",
        edge_id=deployment.target_edge_id or "",
        edge_name=deployment.target_edge_name,
    )

    state_key = f"deployments/{deployment.id}/current/terraform.tfstate"
    has_state = await minio_client.exists(state_key)

    # Preferred source: the last spec saved through the editor (written
    # to MinIO on every POST /manual and PUT /spec). This makes edits
    # survive across reloads even before a Plan/Apply cycle, which is
    # the natural expectation of a Save button.
    spec_key = _spec_key(deployment.id)
    if await minio_client.exists(spec_key):
        try:
            raw = await minio_client.get_text(spec_key)
            spec = DeploymentSpec.model_validate_json(raw)
            # Refresh target from DB in case the row was renamed or a
            # migration backfilled target_vdc_id after the spec was saved.
            spec.target = target
            return EditorData(
                deployment_id=str(deployment.id),
                kind=deployment.kind,
                has_state=has_state,
                spec=spec,
            )
        except Exception:
            logger.exception(
                "editor-data: stored spec invalid, falling back to state id=%s",
                deployment.id,
            )

    if not has_state:
        return EditorData(
            deployment_id=str(deployment.id),
            kind=deployment.kind,
            has_state=False,
            spec=DeploymentSpec(target=target),
        )

    try:
        state_text = await minio_client.get_text(state_key)
        spec = parse_state_text(state_text, target)
    except Exception as exc:  # pragma: no cover - surfaced to caller
        logger.exception("editor-data parse failed id=%s", deployment.id)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse state for deployment {deployment.id}: {exc}",
        ) from exc

    return EditorData(
        deployment_id=str(deployment.id),
        kind=deployment.kind,
        has_state=True,
        spec=spec,
    )
