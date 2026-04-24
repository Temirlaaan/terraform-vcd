"""SQLAlchemy model for saved migration deployments.

A Deployment persists the result of a successful migration HCL generation,
so users can re-open the form with the HCL pre-populated.  ``api_token``
is intentionally never stored — it is sessionStorage-only on the client.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Deployment(Base):
    __tablename__ = "deployments"
    __table_args__ = (
        Index("ix_deployments_target_edge_id", "target_edge_id"),
        Index("ix_deployments_created_by", "created_by"),
        Index("ix_deployments_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="migration")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Source (legacy VCD) — NO api_token, NEVER
    source_host: Mapped[str] = mapped_column(String(255), nullable=False)
    source_edge_uuid: Mapped[str] = mapped_column(String(255), nullable=False)
    source_edge_name: Mapped[str] = mapped_column(String(255), nullable=False)
    verify_ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Target VCD
    target_org: Mapped[str] = mapped_column(String(255), nullable=False)
    target_vdc: Mapped[str] = mapped_column(String(255), nullable=False)
    target_vdc_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_edge_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_edge_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Generated artifact
    hcl: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Metadata
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    # Phase 4: drift sync state
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_drift_check: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
