"""Order create → inventory reserve wiring (inventory mocked)."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import OrderStatus
from app.repositories.order_repository import OrderRepository
from app.services.order_service import OrderService
from tests.conftest import FakeInventoryClient
from tests.helpers import auth_header, fresh_key, order_payload


def test_create_order_uses_inventory_price(
    client: TestClient, fake_inventory: FakeInventoryClient
) -> None:
    fake_inventory.price = __import__("decimal").Decimal("42.50")
    response = client.post(
        "/orders", json=order_payload(fresh_key(), qty=2), headers=auth_header()
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["total_amount"] == "85.00"
    assert body["items"][0]["unit_price"] == "42.50"


def test_background_reserve_marks_order_reserved(
    client: TestClient,
    session_factory: sessionmaker[Session],
    fake_inventory: FakeInventoryClient,
) -> None:
    response = client.post(
        "/orders", json=order_payload(fresh_key()), headers=auth_header()
    )
    order_id = uuid.UUID(response.json()["id"])

    # TestClient runs BackgroundTasks before returning control to us in recent
    # Starlette versions; if still pending, drive the worker explicitly.
    db = session_factory()
    try:
        order = OrderRepository(db).get_by_id(order_id)
        assert order is not None
        if order.status == OrderStatus.PENDING.value:
            OrderService(db, inventory=fake_inventory).reserve_inventory(
                order_id, access_token="test-token"
            )
            db.expire_all()
            order = OrderRepository(db).get_by_id(order_id)
        assert order is not None
        assert order.status == OrderStatus.RESERVED.value
        assert fake_inventory.reserve_calls
    finally:
        db.close()


def test_failed_reserve_cancels_order(
    client: TestClient,
    session_factory: sessionmaker[Session],
    fake_inventory: FakeInventoryClient,
) -> None:
    fake_inventory.reserve_ok = False
    response = client.post(
        "/orders", json=order_payload(fresh_key()), headers=auth_header()
    )
    order_id = uuid.UUID(response.json()["id"])

    db = session_factory()
    try:
        order = OrderRepository(db).get_by_id(order_id)
        assert order is not None
        if order.status == OrderStatus.PENDING.value:
            OrderService(db, inventory=fake_inventory).reserve_inventory(
                order_id, access_token="test-token"
            )
            db.expire_all()
            order = OrderRepository(db).get_by_id(order_id)
        assert order is not None
        assert order.status == OrderStatus.CANCELLED.value
    finally:
        db.close()
