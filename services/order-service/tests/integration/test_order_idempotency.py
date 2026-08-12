"""Tests for FR-10: the same idempotency key must never produce two orders."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.schemas.order import OrderCreate
from app.services.order_service import OrderService
from tests.conftest import FakeInventoryClient
from tests.helpers import auth_header, fresh_key, order_payload


def order_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return connection.execute(text("SELECT COUNT(*) FROM orders")).scalar_one()


def test_a_replayed_request_returns_the_original_order(client: TestClient) -> None:
    headers = auth_header()
    payload = order_payload(fresh_key())

    first = client.post("/orders", json=payload, headers=headers)
    second = client.post("/orders", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_a_replayed_request_does_not_create_a_second_row(
    client: TestClient, engine: Engine
) -> None:
    headers = auth_header()
    payload = order_payload(fresh_key())

    for _ in range(4):
        client.post("/orders", json=payload, headers=headers)

    assert order_count(engine) == 1


def test_the_same_items_with_a_new_key_creates_a_separate_order(
    client: TestClient, engine: Engine
) -> None:
    """A customer genuinely buying the same thing twice must get two orders."""
    headers = auth_header()
    first_payload = order_payload(fresh_key())
    second_payload = dict(first_payload, idempotency_key=fresh_key())

    first = client.post("/orders", json=first_payload, headers=headers)
    second = client.post("/orders", json=second_payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert order_count(engine) == 2


def test_two_users_can_reuse_the_same_idempotency_key(
    client: TestClient, engine: Engine
) -> None:
    """Idempotency is scoped per user — keys are not globally unique."""
    key = fresh_key()
    payload = order_payload(key)

    first = client.post(
        "/orders", json=payload, headers=auth_header(user_id=uuid.uuid4())
    )
    second = client.post(
        "/orders", json=payload, headers=auth_header(user_id=uuid.uuid4())
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert order_count(engine) == 2


def test_simultaneous_requests_with_the_same_key_create_one_order(
    session_factory: sessionmaker[Session],
    engine: Engine,
    fake_inventory: FakeInventoryClient,
) -> None:
    """The unique constraint, not the pre-check, is what makes this safe."""
    user_id = uuid.uuid4()
    payload = OrderCreate(**order_payload(fresh_key()))
    barrier = threading.Barrier(2)

    def attempt() -> tuple[uuid.UUID, bool]:
        db = session_factory()
        try:
            barrier.wait(timeout=10)
            order, created = OrderService(db, inventory=fake_inventory).create_order(
                payload, user_id=user_id, access_token="test-token"
            )
            return order.id, created
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt), pool.submit(attempt)]
        results = [future.result() for future in futures]

    assert len({order_id for order_id, _ in results}) == 1
    assert sum(created for _, created in results) == 1
    assert order_count(engine) == 1
