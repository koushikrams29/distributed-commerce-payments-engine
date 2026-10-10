"""add payment outcome reconciliation

Revision ID: f6a7b8c9d0e1
Revises: b4e8f1a2c3d4
Create Date: 2026-10-10 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "b4e8f1a2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payments", sa.Column("gateway_reference", sa.String(255), nullable=True)
    )
    op.add_column("payments", sa.Column("last_error", sa.String(500), nullable=True))
    op.add_column("payments", sa.Column("context_json", sa.JSON(), nullable=True))
    op.add_column(
        "payments",
        sa.Column("outcome_reported_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_payments_amount_positive", "payments", "amount > 0"
    )
    op.create_check_constraint(
        "ck_payments_status",
        "payments",
        "status IN ('pending', 'unknown', 'succeeded', 'failed', 'refunded')",
    )
    op.create_unique_constraint(
        "uq_ledger_entries_payment_direction",
        "ledger_entries",
        ["payment_id", "direction"],
    )
    op.create_check_constraint(
        "ck_ledger_entries_amount_positive", "ledger_entries", "amount > 0"
    )
    op.create_check_constraint(
        "ck_ledger_entries_direction",
        "ledger_entries",
        "direction IN ('debit', 'credit')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_ledger_entries_direction", "ledger_entries", type_="check"
    )
    op.drop_constraint(
        "ck_ledger_entries_amount_positive", "ledger_entries", type_="check"
    )
    op.drop_constraint(
        "uq_ledger_entries_payment_direction", "ledger_entries", type_="unique"
    )
    op.drop_constraint("ck_payments_status", "payments", type_="check")
    op.drop_constraint("ck_payments_amount_positive", "payments", type_="check")
    op.drop_column("payments", "updated_at")
    op.drop_column("payments", "outcome_reported_at")
    op.drop_column("payments", "context_json")
    op.drop_column("payments", "last_error")
    op.drop_column("payments", "gateway_reference")
