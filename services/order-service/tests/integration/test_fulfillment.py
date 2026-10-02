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


def _outbox(engine: Engine, order_id: uuid.UUID) -> list[tuple[str, dict[str, Any]]]:
    with engine.connect() as connection:
        return [
            (row.event_type, row.payload_json)
            for row in connection.execute(
                text(
                    "SELECT event_type, payload_json FROM outbox "
                    "WHERE aggregate_id = :id ORDER BY created_at"
                ),
                {"id": order_id},
            )
        ]


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
