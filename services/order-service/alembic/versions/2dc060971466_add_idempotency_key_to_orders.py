"""add idempotency_key to orders

Revision ID: 2dc060971466
Revises: e21a1e3f92b8
Create Date: 2026-08-08 17:26:08.202208

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2dc060971466'
down_revision: Union[str, Sequence[str], None] = 'e21a1e3f92b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Added as nullable first: a NOT NULL column cannot be added to a table
    # that already holds rows, because there is no value to put in them.
    op.add_column(
        "orders", sa.Column("idempotency_key", sa.String(length=255), nullable=True)
    )

    # Backfill pre-existing orders. Deriving the value from the primary key
    # keeps it unique without requiring a Postgres extension, and marks these
    # rows as legacy rather than client-supplied.
    op.execute(
        "UPDATE orders "
        "SET idempotency_key = 'backfill-' || id::text "
        "WHERE idempotency_key IS NULL"
    )

    # Only now that every row has a value can the constraints be enforced.
    op.alter_column(
        "orders",
        "idempotency_key",
        existing_type=sa.String(length=255),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_orders_idempotency_key", "orders", ["idempotency_key"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_orders_idempotency_key", "orders", type_="unique")
    op.drop_column("orders", "idempotency_key")
