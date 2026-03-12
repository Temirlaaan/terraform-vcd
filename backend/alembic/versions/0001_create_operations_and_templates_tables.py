"""create operations and templates tables

Revision ID: 0001
Revises:
Create Date: 2026-03-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

operation_type = postgresql.ENUM("PLAN", "APPLY", "DESTROY", name="operation_type", create_type=False)
operation_status = postgresql.ENUM("PENDING", "RUNNING", "SUCCESS", "FAILED", name="operation_status", create_type=False)


def upgrade() -> None:
    op.execute("CREATE TYPE operation_type AS ENUM ('PLAN', 'APPLY', 'DESTROY')")
    op.execute("CREATE TYPE operation_status AS ENUM ('PENDING', 'RUNNING', 'SUCCESS', 'FAILED')")

    op.create_table(
        "operations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("type", operation_type, nullable=False),
        sa.Column("status", operation_status, nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("target_org", sa.String(length=255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("plan_output", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "templates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("templates")
    op.drop_table("operations")
    op.execute("DROP TYPE operation_status")
    op.execute("DROP TYPE operation_type")
