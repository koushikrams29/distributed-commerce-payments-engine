"""scope idempotency_key per user_id

Revision ID: a1f40903c4f7
Revises: 2dc060971466
Create Date: 2026-08-10 20:16:09.633563

"""
from typing import Sequence, Union

from alembic import op


revision: str = "a1f40903c4f7"
down_revision: Union[str, Sequence[str], None] = "2dc060971466"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("uq_orders_idempotency_key", "orders", type_="unique")
    op.create_unique_constraint(
        "uq_orders_user_idempotency_key", "orders", ["user_id", "idempotency_key"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_orders_user_idempotency_key", "orders", type_="unique")
    op.create_unique_constraint(
        "uq_orders_idempotency_key", "orders", ["idempotency_key"]
    )
