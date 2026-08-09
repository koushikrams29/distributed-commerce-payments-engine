import uuid

import pytest
from pydantic import ValidationError

from app.schemas.order import OrderCreate, OrderItemCreate


def _item(qty: int = 1) -> OrderItemCreate:
    return OrderItemCreate(product_id=uuid.uuid4(), qty=qty)


def test_valid_payload_is_accepted() -> None:
    payload = OrderCreate(
        user_id=uuid.uuid4(), idempotency_key="a-valid-key", items=[_item()]
    )
    assert len(payload.items) == 1


def test_order_must_have_at_least_one_item() -> None:
    with pytest.raises(ValidationError):
        OrderCreate(user_id=uuid.uuid4(), idempotency_key="a-valid-key", items=[])


def test_quantity_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        OrderCreate(
            user_id=uuid.uuid4(), idempotency_key="a-valid-key", items=[_item(qty=0)]
        )


def test_idempotency_key_is_required() -> None:
    with pytest.raises(ValidationError):
        OrderCreate(user_id=uuid.uuid4(), items=[_item()])


def test_idempotency_key_must_not_be_trivially_short() -> None:
    with pytest.raises(ValidationError):
        OrderCreate(user_id=uuid.uuid4(), idempotency_key="abc", items=[_item()])
