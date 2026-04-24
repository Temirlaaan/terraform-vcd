import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OperationType(str, enum.Enum):
    PLAN = "PLAN"
    APPLY = "APPLY"
    DESTROY = "DESTROY"
    ROLLBACK = "ROLLBACK"


class OperationStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class Operation(Base):
    __tablename__ = "operations"
    __table_args__ = (
        Index("ix_operations_target_org_started_at", "target_org", "started_at"),
        Index("ix_operations_status", "status"),
        Index("ix_operations_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    type: Mapped[OperationType] = mapped_column(
        Enum(OperationType, name="operation_type"), nullable=False
    )
    status: Mapped[OperationStatus] = mapped_column(
        Enum(OperationStatus, name="operation_status"),
        nullable=False,
        default=OperationStatus.PENDING,
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    target_org: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    plan_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    deployment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    target_edge_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rollback_from_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
