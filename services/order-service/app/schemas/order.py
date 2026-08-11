import uuid
from datetime import datetime
from decimal import Decimal

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
    items: list[OrderItemRead]
