import uuid
from decimal import Decimal

from app.models import OrderStatus
from app.schemas.order import OrderCreate, OrderItemCreate
from app.services.order_service import OrderService


def _payload(*quantities: int) -> OrderCreate:
    return OrderCreate(
        idempotency_key="build-order-key",
        items=[OrderItemCreate(product_id=uuid.uuid4(), qty=qty) for qty in quantities],
    )


def test_total_amount_is_the_sum_of_line_items() -> None:
    payload = _payload(2, 3)
    prices = {item.product_id: Decimal("100.00") for item in payload.items}

    order = OrderService(db=None)._build_order(
        payload, user_id=uuid.uuid4(), prices=prices
    )

    assert order.total_amount == Decimal("500.00")
    assert len(order.items) == 2


def test_new_orders_start_as_pending() -> None:
    payload = _payload(1)
    prices = {payload.items[0].product_id: Decimal("50.00")}

    order = OrderService(db=None)._build_order(
        payload, user_id=uuid.uuid4(), prices=prices
    )

    assert order.status == OrderStatus.PENDING.value


def test_idempotency_key_is_carried_onto_the_order() -> None:
    payload = _payload(1)
    user_id = uuid.uuid4()
    prices = {payload.items[0].product_id: Decimal("10.00")}

    order = OrderService(db=None)._build_order(
        payload, user_id=user_id, prices=prices
    )

    assert order.idempotency_key == payload.idempotency_key
    assert order.user_id == user_id
