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
    ledger_entries: list[LedgerEntryRead]

    @classmethod
    def from_payment(cls, payment) -> "PaymentRead":
        return cls(
            payment_id=payment.id,
            order_id=payment.order_id,
            status=payment.status,
            amount=payment.amount,
            ledger_entries=payment.ledger_entries,
        )
