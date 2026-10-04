import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrderItemCreate(BaseModel):
    product_id: uuid.UUID
    qty: int = Field(gt=0)


class OrderCreate(BaseModel):
    """Request body for creating an order.

    `user_id` is intentionally absent — it comes from the verified JWT so a
    client cannot create orders on another user's behalf.
    """

    idempotency_key: str = Field(min_length=8, max_length=255)
    items: list[OrderItemCreate] = Field(min_length=1)


class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    qty: int
    unit_price: Decimal


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    status: str
    total_amount: Decimal
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemRead]


class OrderListResponse(BaseModel):
    items: list[OrderRead]
    next_cursor: str | None = None


class OrderEventRead(BaseModel):
    """One outbox row: an event this service emitted about an order."""

    id: uuid.UUID
    event_type: str
    payload: dict[str, Any]
    created_at: datetime
    # Null while the row waits for the relay.
    published_at: datetime | None
    # Trace of the request or message that wrote the row, for linking to Jaeger.
    trace_id: str | None


class OutboxBacklog(BaseModel):
    unpublished: int
    oldest_unpublished_at: datetime | None


class OverdueOrders(BaseModel):
    """Orders past the reconciler's timeout for their status."""

    status: str
    count: int
    after_minutes: int


class OrderSummary(BaseModel):
    counts: dict[str, int]
    total: int
    outbox: OutboxBacklog
    overdue: list[OverdueOrders]
    reconciler_enabled: bool
    reconcile_interval_seconds: float
    generated_at: datetime
