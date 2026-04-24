"""SQLAlchemy model for drift sync reports.

A DriftReport row captures the outcome of a single drift-sync run for
one deployment: what changed in VCD vs what dashboard thinks, and
whether an admin has reviewed it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DriftReport(Base):
    __tablename__ = "drift_reports"
    __table_args__ = (
        Index("ix_drift_reports_deployment_ran", "deployment_id", "ran_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    deployment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("deployments.id", ondelete="CASCADE"),
        nullable=False,
    )
    ran_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    has_changes: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    additions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    modifications: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    deletions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    auto_resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reviewed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("deployment_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
