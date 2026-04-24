"""SQLAlchemy model for immutable per-deployment version snapshots.

Each row pairs an HCL snapshot and a Terraform state snapshot stored in
MinIO under ``deployments/<deployment_id>/v<N>/``. Versions are
append-only; rotation removes the oldest non-pinned ones.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DeploymentVersion(Base):
    __tablename__ = "deployment_versions"
    __table_args__ = (
        UniqueConstraint("deployment_id", "version_num", name="uq_dv_deployment_version_num"),
        UniqueConstraint("deployment_id", "state_hash", name="uq_dv_deployment_state_hash"),
        Index("ix_dv_deployment_created_at", "deployment_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    deployment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("deployments.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_num: Mapped[int] = mapped_column(Integer, nullable=False)
    state_hash: Mapped[str] = mapped_column(Text, nullable=False)
    hcl_key: Mapped[str] = mapped_column(Text, nullable=False)
    state_key: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
