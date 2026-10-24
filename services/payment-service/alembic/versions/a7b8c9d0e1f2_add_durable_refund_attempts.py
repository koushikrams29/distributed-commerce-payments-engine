"""add durable refund attempts

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-10-24 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "refund_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("payment_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("gateway_reference", sa.String(255), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("outcome_reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'unknown', 'succeeded', 'failed')",
            name="ck_refund_attempts_status",
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_refund_attempts_idempotency_key"
        ),
        sa.UniqueConstraint("payment_id", name="uq_refund_attempts_payment_id"),
    )
    op.create_index(
        op.f("ix_refund_attempts_payment_id"),
        "refund_attempts",
        ["payment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_refund_attempts_status"),
        "refund_attempts",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_refund_attempts_status"), table_name="refund_attempts")
    op.drop_index(
        op.f("ix_refund_attempts_payment_id"), table_name="refund_attempts"
    )
    op.drop_table("refund_attempts")
