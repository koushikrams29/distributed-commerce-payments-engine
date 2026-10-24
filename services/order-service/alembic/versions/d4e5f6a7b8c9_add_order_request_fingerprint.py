"""add order request fingerprint

Revision ID: d4e5f6a7b8c9
Revises: 5b9e3c1d7a20
Create Date: 2026-10-10 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "5b9e3c1d7a20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing rows are deliberately left null. On their first replay the
    # service compares durable order_items and lazily stores the fingerprint.
    op.add_column(
        "orders", sa.Column("request_fingerprint", sa.String(64), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("orders", "request_fingerprint")
