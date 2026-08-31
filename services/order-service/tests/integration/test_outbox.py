"""Outbox: order.created is written in the same transaction as the order."""

import uuid
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.models import OrderStatus
from app.repositories.order_repository import OrderRepository
from app.schemas.order import OrderCreate, OrderItemCreate
from app.services.order_service import OrderService
from tests.conftest import FakeInventoryClient, FakePaymentClient


def test_create_order_writes_outbox_row_in_same_transaction(
    session_factory: sessionmaker[Session],
    fake_inventory: FakeInventoryClient,
    fake_payment: FakePaymentClient,
    engine,
) -> None:
    product_id = uuid.uuid4()
    payload = OrderCreate(
        idempotency_key="outbox-key",
        items=[OrderItemCreate(product_id=product_id, qty=1)],
    )

    db = session_factory()
    try:
        with patch("app.services.order_service.settings.use_event_bus", True):
            order, created = OrderService(
                db, inventory=fake_inventory, payment=fake_payment
            ).create_order(
                payload,
                user_id=uuid.uuid4(),
                access_token="token",
            )
        assert created is True
        assert order.status == OrderStatus.PENDING.value

        with engine.connect() as connection:
            outbox_count = connection.execute(
                text("SELECT COUNT(*) FROM outbox WHERE aggregate_id = :id"),
                {"id": order.id},
            ).scalar_one()
            assert outbox_count == 1
    finally:
        db.close()
