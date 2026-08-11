"""RBAC: who may call which order endpoints."""

import uuid

from fastapi.testclient import TestClient

from commerce_common.auth import Role
from tests.helpers import auth_header, fresh_key, order_payload


def test_shopper_is_forbidden_from_listing_orders(client: TestClient) -> None:
    response = client.get("/orders", headers=auth_header(role=Role.SHOPPER))

    assert response.status_code == 403
    assert response.json()["detail"] == "insufficient permissions"


def test_admin_can_list_orders(client: TestClient) -> None:
    shopper = auth_header(user_id=uuid.uuid4(), role=Role.SHOPPER)
    client.post("/orders", json=order_payload(fresh_key()), headers=shopper)
    client.post("/orders", json=order_payload(fresh_key()), headers=shopper)

    response = client.get("/orders", headers=auth_header(role=Role.ADMIN))

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"] is None


def test_admin_list_respects_status_filter(client: TestClient) -> None:
    shopper = auth_header(role=Role.SHOPPER)
    client.post("/orders", json=order_payload(fresh_key()), headers=shopper)

    pending = client.get(
        "/orders",
        params={"status": "pending"},
        headers=auth_header(role=Role.ADMIN),
    )
    paid = client.get(
        "/orders",
        params={"status": "paid"},
        headers=auth_header(role=Role.ADMIN),
    )

    assert pending.status_code == 200
    assert len(pending.json()["items"]) == 1
    assert paid.status_code == 200
    assert paid.json()["items"] == []


def test_admin_list_rejects_unknown_status(client: TestClient) -> None:
    response = client.get(
        "/orders",
        params={"status": "not-a-real-status"},
        headers=auth_header(role=Role.ADMIN),
    )

    assert response.status_code == 422


def test_admin_list_paginates_with_cursor(client: TestClient) -> None:
    shopper = auth_header(role=Role.SHOPPER)
    for _ in range(3):
        client.post("/orders", json=order_payload(fresh_key()), headers=shopper)

    admin = auth_header(role=Role.ADMIN)
    first_page = client.get("/orders", params={"limit": 2}, headers=admin)

    assert first_page.status_code == 200
    first_body = first_page.json()
    assert len(first_body["items"]) == 2
    assert first_body["next_cursor"] is not None

    second_page = client.get(
        "/orders",
        params={"limit": 2, "cursor": first_body["next_cursor"]},
        headers=admin,
    )

    assert second_page.status_code == 200
    second_body = second_page.json()
    assert len(second_body["items"]) == 1
    assert second_body["next_cursor"] is None

    first_ids = {item["id"] for item in first_body["items"]}
    second_ids = {item["id"] for item in second_body["items"]}
    assert first_ids.isdisjoint(second_ids)


def test_admin_list_rejects_garbage_cursor(client: TestClient) -> None:
    response = client.get(
        "/orders",
        params={"cursor": "not-a-valid-cursor"},
        headers=auth_header(role=Role.ADMIN),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid cursor"


def test_unauthenticated_list_is_rejected(client: TestClient) -> None:
    response = client.get("/orders")

    assert response.status_code == 401
