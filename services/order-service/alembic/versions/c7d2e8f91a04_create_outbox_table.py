"""create outbox table

Revision ID: c7d2e8f91a04
Revises: a1f40903c4f7
Create Date: 2026-08-31 21:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c7d2e8f91a04"
down_revision: Union[str, Sequence[str], None] = "a1f40903c4f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outbox",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("aggregate_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_outbox_aggregate_id"), "outbox", ["aggregate_id"], unique=False)
    op.create_index(op.f("ix_outbox_event_type"), "outbox", ["event_type"], unique=False)
    op.create_index(op.f("ix_outbox_published_at"), "outbox", ["published_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_outbox_published_at"), table_name="outbox")
    op.drop_index(op.f("ix_outbox_event_type"), table_name="outbox")
    op.drop_index(op.f("ix_outbox_aggregate_id"), table_name="outbox")
    op.drop_table("outbox")
