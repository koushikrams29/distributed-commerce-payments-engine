import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ChargeRequest(BaseModel):
    order_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=255)


class LedgerEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    direction: str
    amount: Decimal
    created_at: datetime


class PaymentRead(BaseModel):
    payment_id: uuid.UUID
    order_id: uuid.UUID
    status: str
    amount: Decimal
    idempotency_key: str
    gateway_reference: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
    ledger_entries: list[LedgerEntryRead]

    @classmethod
    def from_payment(cls, payment) -> "PaymentRead":
        return cls(
            payment_id=payment.id,
            order_id=payment.order_id,
            status=payment.status,
            amount=payment.amount,
            idempotency_key=payment.idempotency_key,
            gateway_reference=payment.gateway_reference,
            last_error=payment.last_error,
            created_at=payment.created_at,
            updated_at=payment.updated_at,
            ledger_entries=sorted(
                payment.ledger_entries, key=lambda entry: entry.created_at
            ),
        )


class PaymentListResponse(BaseModel):
    items: list[PaymentRead]
    next_cursor: str | None = None


class PaymentSummary(BaseModel):
    counts: dict[str, int]
    total: int
    # Ledger totals: debits are money taken from customers, credits money returned.
    captured_amount: Decimal
    refunded_amount: Decimal
    net_amount: Decimal
    generated_at: datetime
