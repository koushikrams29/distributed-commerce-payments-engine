import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.schemas.inventory import ReserveItem
from app.services.inventory_service import (
    InsufficientStockError,
    InventoryService,
    ReservationConflictError,
)
from commerce_common.auth import Role
from tests.helpers import auth_header, reserve_payload, seed_product


def product_stock(engine: Engine, product_id: uuid.UUID) -> int:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT stock_qty FROM products WHERE id = :id"),
            {"id": product_id},
        ).scalar_one()


def test_reserve_decrements_stock(
    client: TestClient, session_factory: sessionmaker[Session], engine: Engine
) -> None:
    product = seed_product(session_factory, stock_qty=5)

    response = client.post(
        "/reservations",
        json=reserve_payload(product_id=product.id, qty=2),
        headers=auth_header(),
    )

    assert response.status_code == 201
    assert len(response.json()["reservations"]) == 1
    assert product_stock(engine, product.id) == 3


def test_reserve_fails_when_stock_is_insufficient(
    client: TestClient, session_factory: sessionmaker[Session], engine: Engine
) -> None:
    product = seed_product(session_factory, stock_qty=1)

    response = client.post(
        "/reservations",
        json=reserve_payload(product_id=product.id, qty=2),
        headers=auth_header(),
    )

    assert response.status_code == 409
    assert product_stock(engine, product.id) == 1


def test_reserve_is_idempotent_for_the_same_order(
    client: TestClient, session_factory: sessionmaker[Session], engine: Engine
) -> None:
    product = seed_product(session_factory, stock_qty=5)
    order_id = uuid.uuid4()
    payload = reserve_payload(product_id=product.id, qty=2, order_id=order_id)

    first = client.post("/reservations", json=payload, headers=auth_header())
    second = client.post("/reservations", json=payload, headers=auth_header())

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["reservations"][0]["id"] == second.json()["reservations"][0]["id"]
    assert product_stock(engine, product.id) == 3


def test_reusing_order_id_with_different_payload_is_refused(
    client: TestClient, session_factory: sessionmaker[Session], engine: Engine
) -> None:
    product = seed_product(session_factory, stock_qty=5)
    order_id = uuid.uuid4()

    first = client.post(
        "/reservations",
        json=reserve_payload(product_id=product.id, qty=2, order_id=order_id),
        headers=auth_header(),
    )
    conflict = client.post(
        "/reservations",
        json=reserve_payload(product_id=product.id, qty=1, order_id=order_id),
        headers=auth_header(),
    )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert product_stock(engine, product.id) == 3


def test_concurrent_duplicate_reservations_deduct_stock_once(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    product = seed_product(session_factory, stock_qty=5)
    order_id = uuid.uuid4()
    barrier = threading.Barrier(2)

    def attempt() -> uuid.UUID:
        with session_factory() as db:
            barrier.wait(timeout=10)
            reservations = InventoryService(db).reserve(
                order_id=order_id,
                items=[ReserveItem(product_id=product.id, qty=2)],
            )
            return reservations[0].id

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt), pool.submit(attempt)]
        ids = [future.result() for future in futures]

    assert ids[0] == ids[1]
    assert product_stock(engine, product.id) == 3


def test_concurrent_conflicting_reservations_do_not_deduct_twice(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    product = seed_product(session_factory, stock_qty=5)
    order_id = uuid.uuid4()
    barrier = threading.Barrier(2)

    def attempt(qty: int) -> str:
        with session_factory() as db:
            barrier.wait(timeout=10)
            try:
                InventoryService(db).reserve(
                    order_id=order_id,
                    items=[ReserveItem(product_id=product.id, qty=qty)],
                )
                return "reserved"
            except ReservationConflictError:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, 1), pool.submit(attempt, 2)]
        results = [future.result() for future in futures]

    assert sorted(results) == ["conflict", "reserved"]
    assert product_stock(engine, product.id) in {3, 4}


def test_concurrent_reservations_do_not_oversell(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    """FR-2: two concurrent buyers for the last unit → exactly one wins."""
    product = seed_product(session_factory, stock_qty=1)
    barrier = threading.Barrier(2)
    results: list[str] = []

    def attempt() -> None:
        db = session_factory()
        try:
            barrier.wait(timeout=10)
            InventoryService(db).reserve(
                order_id=uuid.uuid4(),
                items=[ReserveItem(product_id=product.id, qty=1)],
            )
            results.append("ok")
        except InsufficientStockError:
            results.append("conflict")
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt), pool.submit(attempt)]
        for future in futures:
            future.result()

    assert results.count("ok") == 1
    assert results.count("conflict") == 1
    assert product_stock(engine, product.id) == 0


def test_release_restores_stock(
    client: TestClient, session_factory: sessionmaker[Session], engine: Engine
) -> None:
    product = seed_product(session_factory, stock_qty=4)
    order_id = uuid.uuid4()
    client.post(
        "/reservations",
        json=reserve_payload(product_id=product.id, qty=3, order_id=order_id),
        headers=auth_header(),
    )

    response = client.post(
        f"/reservations/{order_id}/release", headers=auth_header()
    )

    assert response.status_code == 200
    assert response.json()["released_count"] == 1
    assert product_stock(engine, product.id) == 4


def test_admin_can_list_products(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    seed_product(session_factory, name="Alpha", stock_qty=2)
    seed_product(session_factory, name="Beta", stock_qty=3)

    response = client.get("/products", headers=auth_header(role=Role.ADMIN))

    assert response.status_code == 200
    assert len(response.json()["items"]) == 2


def test_shopper_cannot_list_products(client: TestClient) -> None:
    response = client.get("/products", headers=auth_header(role=Role.SHOPPER))

    assert response.status_code == 403


def test_shopper_can_read_a_product_but_not_other_customers_holds(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    product = seed_product(session_factory, name="Checkout Item", stock_qty=4)
    order_id = uuid.uuid4()
    client.post(
        "/reservations",
        json=reserve_payload(product_id=product.id, qty=1, order_id=order_id),
        headers=auth_header(),
    )

    shopper = client.get(f"/products/{product.id}", headers=auth_header(role=Role.SHOPPER))
    admin = client.get(f"/products/{product.id}", headers=auth_header(role=Role.ADMIN))

    assert shopper.status_code == 200
    assert shopper.json()["id"] == str(product.id)
    assert shopper.json()["stock_qty"] == 3
    assert shopper.json()["active_reservations"] == []
    assert [r["order_id"] for r in admin.json()["active_reservations"]] == [str(order_id)]


def test_unknown_product_is_not_found(client: TestClient) -> None:
    response = client.get(f"/products/{uuid.uuid4()}", headers=auth_header(role=Role.SHOPPER))

    assert response.status_code == 404


def test_ensure_product_seeds_once_by_name(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as db:
        first = InventoryService(db).ensure_product(
            name="Seeded Mouse", price=Decimal("25.00"), stock_qty=10
        )
    with session_factory() as db:
        again = InventoryService(db).ensure_product(
            name="Seeded Mouse", price=Decimal("99.00"), stock_qty=1
        )

    assert again.id == first.id
    assert (again.price, again.stock_qty) == (Decimal("25.00"), 10)
