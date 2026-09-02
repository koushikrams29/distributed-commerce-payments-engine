"""create co_purchase_counts and recorded_orders

Revision ID: e9f4a3c2b816
Revises:
Create Date: 2026-09-01 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e9f4a3c2b816"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "co_purchase_counts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("product_id_a", sa.UUID(), nullable=False),
        sa.Column("product_id_b", sa.UUID(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id_a", "product_id_b", name="uq_co_purchase_counts_pair"
        ),
    )
    op.create_table(
        "recorded_orders",
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("order_id"),
    )


def downgrade() -> None:
    op.drop_table("recorded_orders")
    op.drop_table("co_purchase_counts")
