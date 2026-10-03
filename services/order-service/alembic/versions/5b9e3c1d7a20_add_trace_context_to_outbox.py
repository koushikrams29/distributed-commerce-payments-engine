"""add trace_context to outbox

Revision ID: 5b9e3c1d7a20
Revises: c7d2e8f91a04
Create Date: 2026-10-03 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "5b9e3c1d7a20"
down_revision: Union[str, Sequence[str], None] = "c7d2e8f91a04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable: rows written before this migration (or outside any trace)
    # simply start a new trace when relayed.
    op.add_column(
        "outbox",
        sa.Column("trace_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outbox", "trace_context")
