"""Event-driven saga tail: paid → inventory commit → fulfilled, plus compensations."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from commerce_common.events import EventType

from app.models import OrderStatus
from app.repositories.order_repository import OrderRepository
from app.schemas.order import OrderCreate, OrderItemCreate
from app.services.order_service import OrderService
from tests.conftest import FakeInventoryClient, FakePaymentClient


@pytest.fixture(autouse=True)
def event_bus_on() -> Iterator[None]:
    with patch("app.services.order_service.settings.use_event_bus", True):
        yield


def _create_order(
    session_factory: sessionmaker[Session],
    engine: Engine,
    *,
    status: OrderStatus,
) -> uuid.UUID:
    payload = OrderCreate(
        idempotency_key=f"fulfil-{uuid.uuid4().hex}",
        items=[OrderItemCreate(product_id=uuid.uuid4(), qty=1)],
    )
    db = session_factory()
    try:
        order, _ = OrderService(
            db, inventory=FakeInventoryClient(), payment=FakePaymentClient()
        ).create_order(payload, user_id=uuid.uuid4(), access_token="token")
        order_id = order.id
    finally:
        db.close()

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE orders SET status = :status WHERE id = :id"),
            {"status": status.value, "id": order_id},
        )
        connection.execute(text("DELETE FROM outbox WHERE aggregate_id = :id"), {"id": order_id})
    return order_id


def _handle(session_factory: sessionmaker[Session], handler: str, order_id: uuid.UUID) -> None:
    db = session_factory()
    try:
        getattr(OrderService(db), handler)(order_id)
    finally:
        db.close()


def _status(session_factory: sessionmaker[Session], order_id: uuid.UUID) -> str:
    db = session_factory()
    try:
        order = OrderRepository(db).get_by_id(order_id)
        assert order is not None
        return order.status
    finally:
        db.close()


def _outbox(
    engine: Engine, order_id: uuid.UUID, *, include_status_changes: bool = False
) -> list[tuple[str, dict[str, Any]]]:
    """Saga events for the order; dashboard status events are opt-in."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT event_type, payload_json FROM outbox "
                "WHERE aggregate_id = :id ORDER BY created_at"
            ),
            {"id": order_id},
        )
        return [
            (row.event_type, row.payload_json)
            for row in rows
            if include_status_changes
            or row.event_type != EventType.ORDER_STATUS_CHANGED
        ]


def test_reservation_marks_reserved_and_requests_the_charge(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    order_id = _create_order(session_factory, engine, status=OrderStatus.PENDING)

    _handle(session_factory, "on_inventory_reserved", order_id)

    assert _status(session_factory, order_id) == OrderStatus.RESERVED.value
    [(event_type, payload)] = _outbox(engine, order_id)
    assert event_type == EventType.CHARGE_REQUESTED
    assert payload["order_id"] == str(order_id)
    assert payload["amount"] == "100.00"
    # Shoppers pick their own keys, so two shoppers' charges must never share one.
    assert payload["idempotency_key"] == f"order-{order_id}"


def test_payment_success_marks_paid_and_asks_inventory_to_commit(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    order_id = _create_order(session_factory, engine, status=OrderStatus.RESERVED)

    _handle(session_factory, "on_payment_succeeded", order_id)

    assert _status(session_factory, order_id) == OrderStatus.PAID.value
    assert [e for e, _ in _outbox(engine, order_id)] == [EventType.ORDER_PAID]


def test_inventory_commit_fulfils_the_order(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    order_id = _create_order(session_factory, engine, status=OrderStatus.PAID)

    _handle(session_factory, "on_inventory_committed", order_id)

    assert _status(session_factory, order_id) == OrderStatus.FULFILLED.value
    [(event_type, payload)] = _outbox(engine, order_id)
    assert event_type == EventType.ORDER_FULFILLED
    assert payload["order_id"] == str(order_id)
    assert payload["total_amount"] == "100.00"
    assert uuid.UUID(payload["user_id"])


def test_every_transition_emits_a_status_change_for_the_dashboard(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    order_id = _create_order(session_factory, engine, status=OrderStatus.RESERVED)

    _handle(session_factory, "on_payment_succeeded", order_id)
    _handle(session_factory, "on_inventory_committed", order_id)

    changes = [
        payload
        for event_type, payload in _outbox(engine, order_id, include_status_changes=True)
        if event_type == EventType.ORDER_STATUS_CHANGED
    ]
    assert [(c["previous_status"], c["status"]) for c in changes] == [
        ("reserved", "paid"),
        ("paid", "fulfilled"),
    ]
    assert changes[0]["order_id"] == str(order_id)
    assert changes[0]["total_amount"] == "100.00"
    assert changes[0]["occurred_at"]


def test_rejected_transition_emits_no_status_change(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    order_id = _create_order(session_factory, engine, status=OrderStatus.FULFILLED)

    _handle(session_factory, "on_payment_failed", order_id)

    assert _outbox(engine, order_id, include_status_changes=True) == []


def test_redelivered_commit_does_not_fulfil_twice(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    order_id = _create_order(session_factory, engine, status=OrderStatus.PAID)

    _handle(session_factory, "on_inventory_committed", order_id)
    _handle(session_factory, "on_inventory_committed", order_id)

    assert [e for e, _ in _outbox(engine, order_id)] == [EventType.ORDER_FULFILLED]


def test_payment_after_cancellation_requests_a_refund(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    order_id = _create_order(session_factory, engine, status=OrderStatus.CANCELLED)

    _handle(session_factory, "on_payment_succeeded", order_id)

    assert _status(session_factory, order_id) == OrderStatus.CANCELLED.value
    assert [e for e, _ in _outbox(engine, order_id)] == [EventType.REFUND_REQUESTED]


def test_reservation_after_cancellation_releases_the_stock(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    order_id = _create_order(session_factory, engine, status=OrderStatus.CANCELLED)

    _handle(session_factory, "on_inventory_reserved", order_id)

    assert _status(session_factory, order_id) == OrderStatus.CANCELLED.value
    assert [e for e, _ in _outbox(engine, order_id)] == [EventType.ORDER_CANCELLED]


def test_failed_reservation_cancels_without_compensation(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    order_id = _create_order(session_factory, engine, status=OrderStatus.PENDING)

    _handle(session_factory, "on_inventory_failed", order_id)

    assert _status(session_factory, order_id) == OrderStatus.CANCELLED.value
    # Nothing was reserved or charged, so there is nothing to undo.
    assert _outbox(engine, order_id) == []


def test_failed_payment_cancels_and_releases_the_stock(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    order_id = _create_order(session_factory, engine, status=OrderStatus.RESERVED)

    _handle(session_factory, "on_payment_failed", order_id)

    assert _status(session_factory, order_id) == OrderStatus.CANCELLED.value
    [(event_type, payload)] = _outbox(engine, order_id)
    assert event_type == EventType.ORDER_CANCELLED
    assert payload["order_id"] == str(order_id)


@pytest.mark.parametrize(
    ("status", "handler"),
    [
        (OrderStatus.RESERVED, "on_inventory_reserved"),
        (OrderStatus.RESERVED, "on_inventory_failed"),
        (OrderStatus.PAID, "on_payment_succeeded"),
        (OrderStatus.PENDING, "on_payment_failed"),
        (OrderStatus.RESERVED, "on_inventory_committed"),
    ],
)
def test_stale_or_duplicate_events_leave_the_order_alone(
    session_factory: sessionmaker[Session],
    engine: Engine,
    status: OrderStatus,
    handler: str,
) -> None:
    order_id = _create_order(session_factory, engine, status=status)

    _handle(session_factory, handler, order_id)

    assert _status(session_factory, order_id) == status.value
    assert _outbox(engine, order_id, include_status_changes=True) == []


@pytest.mark.parametrize(
    "handler",
    [
        "on_inventory_reserved",
        "on_inventory_failed",
        "on_payment_succeeded",
        "on_payment_failed",
        "on_inventory_committed",
    ],
)
def test_events_for_unknown_orders_are_ignored(
    session_factory: sessionmaker[Session], engine: Engine, handler: str
) -> None:
    order_id = uuid.uuid4()

    _handle(session_factory, handler, order_id)

    assert _outbox(engine, order_id, include_status_changes=True) == []


def test_reconciler_resends_order_paid_for_stuck_paid_orders(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    order_id = _create_order(session_factory, engine, status=OrderStatus.PAID)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE orders SET updated_at = :stale WHERE id = :id"),
            {"stale": datetime.now(UTC) - timedelta(minutes=60), "id": order_id},
        )

    db = session_factory()
    try:
        first = OrderService(db).reconcile_stuck_orders()
        second = OrderService(db).reconcile_stuck_orders()
    finally:
        db.close()

    assert (first, second) == (1, 0)
    assert _status(session_factory, order_id) == OrderStatus.PAID.value
    assert [e for e, _ in _outbox(engine, order_id)] == [EventType.ORDER_PAID]


def test_reconciler_skips_an_order_an_event_handler_has_locked(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    order_id = _create_order(session_factory, engine, status=OrderStatus.RESERVED)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE orders SET created_at = :stale WHERE id = :id"),
            {"stale": datetime.now(UTC) - timedelta(minutes=60), "id": order_id},
        )

    handler_db = session_factory()
    reconciler_db = session_factory()
    try:
        assert OrderRepository(handler_db).get_by_id_for_update(order_id) is not None

        assert OrderService(reconciler_db).reconcile_stuck_orders() == 0
    finally:
        handler_db.rollback()
        handler_db.close()
        reconciler_db.close()

    assert _status(session_factory, order_id) == OrderStatus.RESERVED.value
