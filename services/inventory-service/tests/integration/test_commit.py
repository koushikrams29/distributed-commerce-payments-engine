import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.services.inventory_service import InventoryService
from tests.helpers import auth_header, reserve_payload, seed_product
from tests.integration.test_reservations import product_stock


def reservation_statuses(engine: Engine, order_id: uuid.UUID) -> list[str]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text("SELECT status FROM stock_reservations WHERE order_id = :id"),
                {"id": order_id},
            ).scalars()
        )


def _reserve(client: TestClient, product_id: uuid.UUID, qty: int) -> uuid.UUID:
    order_id = uuid.uuid4()
    response = client.post(
        "/reservations",
        json=reserve_payload(product_id=product_id, qty=qty, order_id=order_id),
        headers=auth_header(),
    )
    assert response.status_code == 201
    return order_id


def test_commit_keeps_stock_deducted_and_marks_reservation_committed(
    client: TestClient, session_factory: sessionmaker[Session], engine: Engine
) -> None:
    product = seed_product(session_factory, stock_qty=5)
    order_id = _reserve(client, product.id, qty=2)

    response = client.post(f"/reservations/{order_id}/commit", headers=auth_header())

    assert response.status_code == 200
    assert response.json()["committed_count"] == 1
    assert reservation_statuses(engine, order_id) == ["committed"]
    assert product_stock(engine, product.id) == 3


def test_commit_is_idempotent(
    client: TestClient, session_factory: sessionmaker[Session], engine: Engine
) -> None:
    product = seed_product(session_factory, stock_qty=5)
    order_id = _reserve(client, product.id, qty=2)

    client.post(f"/reservations/{order_id}/commit", headers=auth_header())
    second = client.post(f"/reservations/{order_id}/commit", headers=auth_header())

    assert second.json()["committed_count"] == 0
    assert product_stock(engine, product.id) == 3


def test_release_after_commit_does_not_restock_paid_units(
    client: TestClient, session_factory: sessionmaker[Session], engine: Engine
) -> None:
    product = seed_product(session_factory, stock_qty=5)
    order_id = _reserve(client, product.id, qty=2)
    client.post(f"/reservations/{order_id}/commit", headers=auth_header())

    response = client.post(f"/reservations/{order_id}/release", headers=auth_header())

    assert response.json()["released_count"] == 0
    assert product_stock(engine, product.id) == 3


def test_replayed_reservation_after_commit_does_not_deduct_again(
    client: TestClient, session_factory: sessionmaker[Session], engine: Engine
) -> None:
    product = seed_product(session_factory, stock_qty=5)
    order_id = _reserve(client, product.id, qty=2)
    client.post(f"/reservations/{order_id}/commit", headers=auth_header())

    replay = client.post(
        "/reservations",
        json=reserve_payload(product_id=product.id, qty=2, order_id=order_id),
        headers=auth_header(),
    )

    assert replay.status_code == 201
    assert product_stock(engine, product.id) == 3


def test_concurrent_commit_and_release_cannot_both_win(
    client: TestClient, session_factory: sessionmaker[Session], engine: Engine
) -> None:
    product = seed_product(session_factory, stock_qty=5)
    order_id = _reserve(client, product.id, qty=2)
    barrier = threading.Barrier(2)
    outcomes: dict[str, int] = {}

    def run(action: str) -> None:
        db = session_factory()
        try:
            service = InventoryService(db)
            barrier.wait(timeout=10)
            if action == "commit":
                outcomes[action] = service.commit_for_order(order_id)
            else:
                outcomes[action] = service.release_for_order(order_id)
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(run, "commit"), pool.submit(run, "release")]:
            future.result()

    assert sorted(outcomes.values()) == [0, 1]
    statuses = reservation_statuses(engine, order_id)
    if outcomes["commit"] == 1:
        assert statuses == ["committed"]
        assert product_stock(engine, product.id) == 3
    else:
        assert statuses == ["released"]
        assert product_stock(engine, product.id) == 5
