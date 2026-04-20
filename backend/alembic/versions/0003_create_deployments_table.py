"""create deployments table

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "deployments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="migration"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_host", sa.String(length=255), nullable=False),
        sa.Column("source_edge_uuid", sa.String(length=255), nullable=False),
        sa.Column("source_edge_name", sa.String(length=255), nullable=False),
        sa.Column("verify_ssl", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("target_org", sa.String(length=255), nullable=False),
        sa.Column("target_vdc", sa.String(length=255), nullable=False),
        sa.Column("target_vdc_id", sa.String(length=255), nullable=False),
        sa.Column("target_edge_id", sa.String(length=255), nullable=False),
        sa.Column("hcl", sa.Text(), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deployments_target_edge_id", "deployments", ["target_edge_id"])
    op.create_index("ix_deployments_created_by", "deployments", ["created_by"])
    op.create_index("ix_deployments_created_at", "deployments", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_deployments_created_at", table_name="deployments")
    op.drop_index("ix_deployments_created_by", table_name="deployments")
    op.drop_index("ix_deployments_target_edge_id", table_name="deployments")
    op.drop_table("deployments")
