"""create notifications

Revision ID: d8e3f2b1a905
Revises:
Create Date: 2026-08-31 22:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8e3f2b1a905"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "channel", name="uq_notifications_order_channel"),
    )
    op.create_index(
        op.f("ix_notifications_order_id"), "notifications", ["order_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_notifications_order_id"), table_name="notifications")
    op.drop_table("notifications")
