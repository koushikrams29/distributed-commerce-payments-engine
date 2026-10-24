"""Tests for FR-10: the same idempotency key must never produce two orders."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.schemas.order import OrderCreate
from app.services.order_service import IdempotencyKeyReusedError, OrderService
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


def test_reusing_a_key_with_a_different_quantity_returns_conflict(
    client: TestClient, engine: Engine
) -> None:
    headers = auth_header()
    key = fresh_key()
    payload = order_payload(key, qty=2)

    first = client.post("/orders", json=payload, headers=headers)
    conflict = client.post(
        "/orders",
        json={**payload, "items": [{**payload["items"][0], "qty": 3}]},
        headers=headers,
    )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert "different order payload" in conflict.json()["detail"]
    assert order_count(engine) == 1


def test_reusing_a_key_with_a_different_product_returns_conflict(
    client: TestClient, engine: Engine
) -> None:
    headers = auth_header()
    key = fresh_key()
    first_payload = order_payload(key)
    other_payload = order_payload(key)

    first = client.post("/orders", json=first_payload, headers=headers)
    conflict = client.post("/orders", json=other_payload, headers=headers)

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert order_count(engine) == 1


def test_item_order_and_split_lines_have_the_same_fingerprint(
    client: TestClient
) -> None:
    headers = auth_header()
    key = fresh_key()
    first_product, second_product = uuid.uuid4(), uuid.uuid4()
    first_payload = {
        "idempotency_key": key,
        "items": [
            {"product_id": str(first_product), "qty": 1},
            {"product_id": str(second_product), "qty": 2},
            {"product_id": str(first_product), "qty": 2},
        ],
    }
    equivalent_payload = {
        "idempotency_key": key,
        "items": [
            {"product_id": str(second_product), "qty": 2},
            {"product_id": str(first_product), "qty": 3},
        ],
    }

    first = client.post("/orders", json=first_payload, headers=headers)
    replay = client.post("/orders", json=equivalent_payload, headers=headers)

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]


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


def test_simultaneous_conflicting_requests_create_one_order_and_one_conflict(
    session_factory: sessionmaker[Session],
    engine: Engine,
    fake_inventory: FakeInventoryClient,
) -> None:
    user_id = uuid.uuid4()
    key = fresh_key()
    product_id = uuid.uuid4()
    payloads = [
        OrderCreate(
            idempotency_key=key,
            items=[{"product_id": product_id, "qty": qty}],
        )
        for qty in (1, 2)
    ]
    barrier = threading.Barrier(2)

    def attempt(payload: OrderCreate) -> str:
        with session_factory() as db:
            barrier.wait(timeout=10)
            try:
                service = OrderService(db, inventory=fake_inventory)
                _, created = service.create_order(
                    payload, user_id=user_id, access_token="test-token"
                )
                return "created" if created else "replayed"
            except IdempotencyKeyReusedError:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, payload) for payload in payloads]
        results = [future.result() for future in futures]

    assert sorted(results) == ["conflict", "created"]
    assert order_count(engine) == 1
