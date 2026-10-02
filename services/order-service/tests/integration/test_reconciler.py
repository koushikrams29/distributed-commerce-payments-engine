"""FR-5: stuck pending/reserved orders are cancelled by the reconciler."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from commerce_common.events import EventType
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.models import OrderStatus
from app.repositories.order_repository import OrderRepository
from app.schemas.order import OrderCreate, OrderItemCreate
from app.services.order_service import OrderService
from tests.conftest import FakeInventoryClient, FakePaymentClient


def _create_pending_order(
    session_factory: sessionmaker[Session],
    fake_inventory: FakeInventoryClient,
    fake_payment: FakePaymentClient,
) -> uuid.UUID:
    product_id = uuid.uuid4()
    payload = OrderCreate(
        idempotency_key=f"reconcile-{uuid.uuid4().hex}",
        items=[OrderItemCreate(product_id=product_id, qty=1)],
    )
    db = session_factory()
    try:
        order, _ = OrderService(
            db, inventory=fake_inventory, payment=fake_payment
        ).create_order(
            payload,
            user_id=uuid.uuid4(),
            access_token="test-token",
        )
        return order.id
    finally:
        db.close()


def test_reconciler_cancels_stuck_pending_orders(
    session_factory: sessionmaker[Session],
    engine,
    fake_inventory: FakeInventoryClient,
    fake_payment: FakePaymentClient,
) -> None:
    order_id = _create_pending_order(
        session_factory, fake_inventory, fake_payment
    )
    stale = datetime.now(UTC) - timedelta(minutes=60)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE orders SET created_at = :stale WHERE id = :id"),
            {"stale": stale, "id": order_id},
        )

    db = session_factory()
    try:
        with patch("app.services.order_service.settings.reconcile_pending_after_minutes", 30):
            cancelled = OrderService(db).reconcile_stuck_orders()
        assert cancelled == 1
        order = OrderRepository(db).get_by_id(order_id)
        assert order is not None
        assert order.status == OrderStatus.CANCELLED.value
    finally:
        db.close()


def test_reconciler_cancels_stuck_reserved_and_enqueues_release(
    session_factory: sessionmaker[Session],
    engine,
    fake_inventory: FakeInventoryClient,
    fake_payment: FakePaymentClient,
) -> None:
    order_id = _create_pending_order(
        session_factory, fake_inventory, fake_payment
    )
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE orders SET status = 'reserved' WHERE id = :id"),
            {"id": order_id},
        )
        connection.execute(
            text(
                "UPDATE orders SET created_at = :stale WHERE id = :id"
            ),
            {"stale": datetime.now(UTC) - timedelta(minutes=60), "id": order_id},
        )

    db = session_factory()
    try:
        with (
            patch("app.services.order_service.settings.reconcile_reserved_after_minutes", 30),
            patch("app.services.order_service.settings.use_event_bus", True),
        ):
            cancelled = OrderService(db).reconcile_stuck_orders()
        assert cancelled == 1
        order = OrderRepository(db).get_by_id(order_id)
        assert order is not None
        assert order.status == OrderStatus.CANCELLED.value
    finally:
        db.close()

    with engine.connect() as connection:
        event_type = connection.execute(
            text(
                "SELECT event_type FROM outbox WHERE aggregate_id = :id"
            ),
            {"id": order_id},
        ).scalar_one()
        assert event_type == EventType.ORDER_CANCELLED


def test_reconciler_ignores_recent_orders(
    session_factory: sessionmaker[Session],
    fake_inventory: FakeInventoryClient,
    fake_payment: FakePaymentClient,
) -> None:
    order_id = _create_pending_order(
        session_factory, fake_inventory, fake_payment
    )
    db = session_factory()
    try:
        cancelled = OrderService(db).reconcile_stuck_orders()
        assert cancelled == 0
        order = OrderRepository(db).get_by_id(order_id)
        assert order is not None
        assert order.status == OrderStatus.PENDING.value
    finally:
        db.close()
