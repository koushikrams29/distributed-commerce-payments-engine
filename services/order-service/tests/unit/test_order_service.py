import uuid

from app.models import OrderStatus
from app.schemas.order import OrderCreate, OrderItemCreate
from app.services.order_service import PLACEHOLDER_UNIT_PRICE, OrderService


def _payload(*quantities: int) -> OrderCreate:
    return OrderCreate(
        user_id=uuid.uuid4(),
        idempotency_key="build-order-key",
        items=[OrderItemCreate(product_id=uuid.uuid4(), qty=qty) for qty in quantities],
    )


def test_total_amount_is_the_sum_of_line_items() -> None:
    order = OrderService(db=None)._build_order(_payload(2, 3))

    assert order.total_amount == PLACEHOLDER_UNIT_PRICE * 5
    assert len(order.items) == 2


def test_new_orders_start_as_pending() -> None:
    order = OrderService(db=None)._build_order(_payload(1))

    assert order.status == OrderStatus.PENDING.value


def test_idempotency_key_is_carried_onto_the_order() -> None:
    payload = _payload(1)

    order = OrderService(db=None)._build_order(payload)

    assert order.idempotency_key == payload.idempotency_key
