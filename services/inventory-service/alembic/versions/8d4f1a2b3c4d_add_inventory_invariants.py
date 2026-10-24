"""add inventory database invariants

Revision ID: 8d4f1a2b3c4d
Revises: 321c79cd319d
Create Date: 2026-10-24 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "8d4f1a2b3c4d"
down_revision: Union[str, Sequence[str], None] = "321c79cd319d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("seed_key", sa.String(255), nullable=True))
    # Preserve idempotent startup behavior for existing uniquely named seed rows.
    op.execute(
        """
        UPDATE products AS product
        SET seed_key = product.name
        WHERE NOT EXISTS (
            SELECT 1 FROM products AS duplicate
            WHERE duplicate.name = product.name AND duplicate.id <> product.id
        )
        """
    )
    op.create_unique_constraint("uq_products_seed_key", "products", ["seed_key"])
    op.create_check_constraint("ck_products_price_positive", "products", "price > 0")
    op.create_check_constraint(
        "ck_products_stock_nonnegative", "products", "stock_qty >= 0"
    )
    op.create_check_constraint(
        "ck_stock_reservations_qty_positive", "stock_reservations", "qty > 0"
    )
    op.create_check_constraint(
        "ck_stock_reservations_status",
        "stock_reservations",
        "status IN ('held', 'released', 'committed')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_stock_reservations_status", "stock_reservations", type_="check"
    )
    op.drop_constraint(
        "ck_stock_reservations_qty_positive", "stock_reservations", type_="check"
    )
    op.drop_constraint("ck_products_stock_nonnegative", "products", type_="check")
    op.drop_constraint("ck_products_price_positive", "products", type_="check")
    op.drop_constraint("uq_products_seed_key", "products", type_="unique")
    op.drop_column("products", "seed_key")
