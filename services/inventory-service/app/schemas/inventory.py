import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ReserveItem(BaseModel):
    product_id: uuid.UUID
    qty: int = Field(gt=0)


class ReserveRequest(BaseModel):
    order_id: uuid.UUID
    items: list[ReserveItem] = Field(min_length=1)


class ReservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_id: uuid.UUID
    product_id: uuid.UUID
    qty: int
    status: str
    expires_at: datetime


class ReserveResponse(BaseModel):
    order_id: uuid.UUID
    reservations: list[ReservationRead]


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    price: Decimal
    stock_qty: int


class ProductDetail(ProductRead):
    active_reservations: list[ReservationRead] = []


class ProductStock(ProductRead):
    """A product with where its units are.

    stock_qty is what can still be reserved; held units were already deducted
    from it, and committed units are sold.
    """

    reserved_qty: int
    committed_qty: int


class ProductListResponse(BaseModel):
    items: list[ProductStock]


class ReservationActivity(ReservationRead):
    product_name: str
    created_at: datetime


class ReservationListResponse(BaseModel):
    items: list[ReservationActivity]
