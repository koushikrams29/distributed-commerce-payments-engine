"""Order create → inventory reserve wiring (inventory mocked)."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import OrderStatus
from app.repositories.order_repository import OrderRepository
from app.services.order_service import OrderService
from tests.conftest import FakeInventoryClient, FakePaymentClient
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


def test_background_flow_reserves_charges_and_fulfils(
    client: TestClient,
    session_factory: sessionmaker[Session],
    fake_inventory: FakeInventoryClient,
    fake_payment: FakePaymentClient,
) -> None:
    response = client.post(
        "/orders", json=order_payload(fresh_key()), headers=auth_header()
    )
    order_id = uuid.UUID(response.json()["id"])

    db = session_factory()
    try:
        order = OrderRepository(db).get_by_id(order_id)
        assert order is not None
        assert order.status == OrderStatus.FULFILLED.value
        assert fake_inventory.reserve_calls == [order_id]
        assert fake_payment.charge_calls == [order_id]
        assert fake_inventory.commit_calls == [order_id]
    finally:
        db.close()


def test_order_stays_paid_when_inventory_commit_is_unreachable(
    session_factory: sessionmaker[Session],
    fake_inventory: FakeInventoryClient,
    fake_payment: FakePaymentClient,
    client: TestClient,
) -> None:
    from app.clients.inventory import InventoryUnavailableError

    def unreachable(*, order_id: uuid.UUID, access_token: str) -> None:
        raise InventoryUnavailableError("down")

    fake_inventory.commit = unreachable  # type: ignore[method-assign]
    response = client.post(
        "/orders", json=order_payload(fresh_key()), headers=auth_header()
    )
    order_id = uuid.UUID(response.json()["id"])

    db = session_factory()
    try:
        order = OrderRepository(db).get_by_id(order_id)
        assert order is not None
        assert order.status == OrderStatus.PAID.value
    finally:
        db.close()


def test_failed_reserve_cancels_order(
    client: TestClient,
    session_factory: sessionmaker[Session],
    fake_inventory: FakeInventoryClient,
    fake_payment: FakePaymentClient,
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
            OrderService(
                db, inventory=fake_inventory, payment=fake_payment
            ).reserve_inventory(order_id, access_token="test-token")
            db.expire_all()
            order = OrderRepository(db).get_by_id(order_id)
        assert order is not None
        assert order.status == OrderStatus.CANCELLED.value
    finally:
        db.close()


def test_failed_payment_cancels_and_releases_stock(
    client: TestClient,
    session_factory: sessionmaker[Session],
    fake_inventory: FakeInventoryClient,
    fake_payment: FakePaymentClient,
) -> None:
    fake_payment.charge_ok = False
    response = client.post(
        "/orders", json=order_payload(fresh_key()), headers=auth_header()
    )
    order_id = uuid.UUID(response.json()["id"])

    db = session_factory()
    try:
        service = OrderService(db, inventory=fake_inventory, payment=fake_payment)
        order = OrderRepository(db).get_by_id(order_id)
        assert order is not None
        if order.status == OrderStatus.PENDING.value:
            service.reserve_inventory(order_id, access_token="test-token")
        db.expire_all()
        order = OrderRepository(db).get_by_id(order_id)
        assert order is not None
        if order.status == OrderStatus.RESERVED.value:
            service.charge_payment(order_id, access_token="test-token")
        db.expire_all()
        order = OrderRepository(db).get_by_id(order_id)
        assert order is not None
        assert order.status == OrderStatus.CANCELLED.value
        assert fake_inventory.release_calls == [order_id]
    finally:
        db.close()
