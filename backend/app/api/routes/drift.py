"""Drift sync API routes.

- ``POST /deployments/{id}/drift-check`` — run drift sync now (admin).
- ``GET  /deployments/{id}/drift-reports`` — list reports for deployment.
- ``GET  /drift-reports/{id}`` — fetch a single report in full.
- ``POST /drift-reports/{id}/review`` — record admin review (accept/rollback/ignore).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthenticatedUser, require_roles
from app.database import get_db
from app.jobs.drift_sync import sync_deployment
from app.models.deployment import Deployment
from app.models.deployment_version import DeploymentVersion
from app.models.drift_report import DriftReport

logger = logging.getLogger(__name__)

_ADMIN_ONLY = require_roles("tf-admin")
_READER = require_roles("tf-admin", "tf-operator", "tf-viewer")

router = APIRouter(tags=["drift"])


class DriftReportSummary(BaseModel):
    id: uuid.UUID
    deployment_id: uuid.UUID
    ran_at: datetime
    has_changes: bool | None
    additions_count: int
    modifications_count: int
    deletions_count: int
    auto_resolved: bool
    resolution: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    error: str | None
    version_id: uuid.UUID | None = None
    version_num: int | None = None


class DriftReportDetail(DriftReportSummary):
    additions: list
    modifications: list
    deletions: list


class ReviewBody(BaseModel):
    resolution: str = Field(..., pattern="^(accepted|rolled_back|ignored)$")


class TriggerResponse(BaseModel):
    deployment_id: uuid.UUID
    triggered: bool
    message: str


def _to_summary(
    r: DriftReport, version_num: int | None = None,
) -> DriftReportSummary:
    return DriftReportSummary(
        id=r.id,
        deployment_id=r.deployment_id,
        ran_at=r.ran_at,
        has_changes=r.has_changes,
        additions_count=len(r.additions or []),
        modifications_count=len(r.modifications or []),
        deletions_count=len(r.deletions or []),
        auto_resolved=r.auto_resolved,
        resolution=r.resolution,
        reviewed_by=r.reviewed_by,
        reviewed_at=r.reviewed_at,
        error=r.error,
        version_id=r.version_id,
        version_num=version_num,
    )


async def _version_num_map(
    db: AsyncSession, version_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not version_ids:
        return {}
    result = await db.execute(
        select(DeploymentVersion.id, DeploymentVersion.version_num)
        .where(DeploymentVersion.id.in_(version_ids))
    )
    return {row[0]: row[1] for row in result.all()}


@router.post(
    "/deployments/{deployment_id}/drift-check",
    response_model=TriggerResponse,
)
async def trigger_drift_check(
    deployment_id: uuid.UUID,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_ADMIN_ONLY),  # noqa: ARG001
) -> TriggerResponse:
    deployment = await db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(status_code=404, detail="Deployment not found")

    async def _run():
        try:
            await sync_deployment(deployment_id, triggered_by=f"manual:{user.username}")
        except Exception:
            logger.exception("Manual drift_sync crashed for %s", deployment_id)

    background.add_task(_run)
    return TriggerResponse(
        deployment_id=deployment_id,
        triggered=True,
        message="Drift check scheduled",
    )


@router.get(
    "/deployments/{deployment_id}/drift-reports",
    response_model=list[DriftReportSummary],
)
async def list_drift_reports(
    deployment_id: uuid.UUID,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_READER),  # noqa: ARG001
) -> list[DriftReportSummary]:
    result = await db.execute(
        select(DriftReport)
        .where(DriftReport.deployment_id == deployment_id)
        .order_by(DriftReport.ran_at.desc())
        .limit(max(1, min(limit, 100)))
    )
    rows = result.scalars().all()
    vmap = await _version_num_map(db, [r.version_id for r in rows if r.version_id])
    return [_to_summary(r, vmap.get(r.version_id) if r.version_id else None) for r in rows]


@router.get("/drift-reports/{report_id}", response_model=DriftReportDetail)
async def get_drift_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_READER),  # noqa: ARG001
) -> DriftReportDetail:
    row = await db.get(DriftReport, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    vnum: int | None = None
    if row.version_id:
        vmap = await _version_num_map(db, [row.version_id])
        vnum = vmap.get(row.version_id)
    base = _to_summary(row, vnum).model_dump()
    return DriftReportDetail(
        **base,
        additions=row.additions or [],
        modifications=row.modifications or [],
        deletions=row.deletions or [],
    )


@router.post("/drift-reports/{report_id}/review", response_model=DriftReportSummary)
async def review_drift_report(
    report_id: uuid.UUID,
    body: ReviewBody,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(_ADMIN_ONLY),
) -> DriftReportSummary:
    row = await db.get(DriftReport, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if row.resolution in {"skipped_locked", "errored"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Report has terminal resolution: {row.resolution}",
        )
    row.resolution = body.resolution
    row.reviewed_by = user.username
    row.reviewed_at = datetime.now(timezone.utc)

    # Option 2-partial: 'ignored' means the drift snapshot is noise that
    # should be hidden from version history. Tag its snapshot with
    # label='dismissed' so the UI can filter it out. Only stamp when no
    # prior label so we don't overwrite apply/rollback/migration labels.
    if body.resolution == "ignored" and row.version_id:
        version = await db.get(DeploymentVersion, row.version_id)
        if version is not None and not version.label:
            version.label = "dismissed"

    # If this was the last outstanding report for the deployment, clear needs_review.
    deployment = await db.get(Deployment, row.deployment_id)
    if deployment is not None:
        pending = await db.execute(
            select(DriftReport.id)
            .where(DriftReport.deployment_id == row.deployment_id)
            .where(DriftReport.id != row.id)
            .where(DriftReport.has_changes.is_(True))
            .where(DriftReport.resolution.is_(None))
            .limit(1)
        )
        if pending.scalar_one_or_none() is None:
            deployment.needs_review = False

    await db.commit()
    await db.refresh(row)
    vnum: int | None = None
    if row.version_id:
        vmap = await _version_num_map(db, [row.version_id])
        vnum = vmap.get(row.version_id)
    return _to_summary(row, vnum)
