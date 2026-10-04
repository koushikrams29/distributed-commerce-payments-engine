"""Admin read views: where each product's units are, and reservation activity."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from commerce_common.auth import Role
from tests.helpers import auth_header, reserve_payload, seed_product


def _reserve(client: TestClient, product_id: uuid.UUID, qty: int) -> uuid.UUID:
    order_id = uuid.uuid4()
    response = client.post(
        "/reservations",
        json=reserve_payload(product_id=product_id, qty=qty, order_id=order_id),
        headers=auth_header(),
    )
    assert response.status_code == 201
    return order_id


def test_products_show_available_reserved_and_committed_units(
    client: TestClient, session_factory: sessionmaker[Session], engine: Engine
) -> None:
    product = seed_product(session_factory, stock_qty=10, name="Mechanical keyboard")
    _reserve(client, product.id, 2)
    sold = _reserve(client, product.id, 3)
    released = _reserve(client, product.id, 1)
    client.post(f"/reservations/{sold}/commit", headers=auth_header())
    client.post(f"/reservations/{released}/release", headers=auth_header())

    items = client.get("/products", headers=auth_header()).json()["items"]

    assert items == [
        {
            "id": str(product.id),
            "name": "Mechanical keyboard",
            "price": "100.00",
            "stock_qty": 5,
            "reserved_qty": 2,
            "committed_qty": 3,
        }
    ]


def test_a_product_without_reservations_has_nothing_held(
    client: TestClient, session_factory: sessionmaker[Session], engine: Engine
) -> None:
    seed_product(session_factory, stock_qty=4)

    (item,) = client.get("/products", headers=auth_header()).json()["items"]

    assert (item["stock_qty"], item["reserved_qty"], item["committed_qty"]) == (4, 0, 0)


def test_reservations_are_listed_newest_first_with_product_names(
    client: TestClient, session_factory: sessionmaker[Session], engine: Engine
) -> None:
    product = seed_product(session_factory, stock_qty=10, name="USB-C dock")
    first = _reserve(client, product.id, 1)
    second = _reserve(client, product.id, 2)

    items = client.get("/reservations", headers=auth_header()).json()["items"]

    assert [item["order_id"] for item in items] == [str(second), str(first)]
    assert items[0]["product_name"] == "USB-C dock"
    assert items[0]["status"] == "held"
    assert "created_at" in items[0] and "expires_at" in items[0]


def test_reservations_filter_by_order_and_status(
    client: TestClient, session_factory: sessionmaker[Session], engine: Engine
) -> None:
    product = seed_product(session_factory, stock_qty=10)
    kept = _reserve(client, product.id, 1)
    released = _reserve(client, product.id, 1)
    client.post(f"/reservations/{released}/release", headers=auth_header())

    by_order = client.get(
        "/reservations", params={"order_id": str(kept)}, headers=auth_header()
    ).json()["items"]
    by_status = client.get(
        "/reservations", params={"status": "released"}, headers=auth_header()
    ).json()["items"]

    assert [item["order_id"] for item in by_order] == [str(kept)]
    assert [item["order_id"] for item in by_status] == [str(released)]


def test_reservations_reject_an_unknown_status(client: TestClient, engine: Engine) -> None:
    response = client.get("/reservations", params={"status": "lost"}, headers=auth_header())

    assert response.status_code == 422


@pytest.mark.parametrize("path", ["/products", "/reservations"])
def test_admin_views_are_admin_only(client: TestClient, engine: Engine, path: str) -> None:
    response = client.get(path, headers=auth_header(role=Role.SHOPPER))

    assert response.status_code == 403
