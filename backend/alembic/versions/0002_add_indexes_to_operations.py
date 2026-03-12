"""add indexes to operations table

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-12
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_operations_target_org_started_at", "operations", ["target_org", "started_at"])
    op.create_index("ix_operations_status", "operations", ["status"])
    op.create_index("ix_operations_user_id", "operations", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_operations_user_id", table_name="operations")
    op.drop_index("ix_operations_status", table_name="operations")
    op.drop_index("ix_operations_target_org_started_at", table_name="operations")
