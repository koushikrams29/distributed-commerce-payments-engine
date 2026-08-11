import uuid
from decimal import Decimal

from fastapi.testclient import TestClient

from app.services.order_service import PLACEHOLDER_UNIT_PRICE
from commerce_common.auth import Role
from tests.helpers import auth_header, fresh_key, order_payload


def test_creating_an_order_returns_201(client: TestClient) -> None:
    response = client.post(
        "/orders", json=order_payload(fresh_key()), headers=auth_header()
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert Decimal(str(body["total_amount"])) == PLACEHOLDER_UNIT_PRICE * 2
    assert len(body["items"]) == 1


def test_creating_an_order_without_a_token_is_rejected(client: TestClient) -> None:
    response = client.post("/orders", json=order_payload(fresh_key()))

    assert response.status_code == 401


def test_a_created_order_can_be_read_back(client: TestClient) -> None:
    user_id = uuid.uuid4()
    headers = auth_header(user_id=user_id)
    created = client.post(
        "/orders", json=order_payload(fresh_key()), headers=headers
    ).json()

    response = client.get(f"/orders/{created['id']}", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
    assert response.json()["user_id"] == str(user_id)


def test_a_shopper_cannot_read_another_users_order(client: TestClient) -> None:
    owner_headers = auth_header(user_id=uuid.uuid4())
    created = client.post(
        "/orders", json=order_payload(fresh_key()), headers=owner_headers
    ).json()

    other_headers = auth_header(user_id=uuid.uuid4())
    response = client.get(f"/orders/{created['id']}", headers=other_headers)

    assert response.status_code == 404


def test_an_admin_can_read_any_order(client: TestClient) -> None:
    owner_headers = auth_header(user_id=uuid.uuid4(), role=Role.SHOPPER)
    created = client.post(
        "/orders", json=order_payload(fresh_key()), headers=owner_headers
    ).json()

    admin_headers = auth_header(user_id=uuid.uuid4(), role=Role.ADMIN)
    response = client.get(f"/orders/{created['id']}", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_reading_an_unknown_order_returns_404(client: TestClient) -> None:
    response = client.get(f"/orders/{uuid.uuid4()}", headers=auth_header())

    assert response.status_code == 404
    assert response.json()["detail"] == "Order not found"


def test_an_order_without_an_idempotency_key_is_rejected(client: TestClient) -> None:
    payload = order_payload(fresh_key())
    del payload["idempotency_key"]

    response = client.post("/orders", json=payload, headers=auth_header())

    assert response.status_code == 422


def test_an_order_without_items_is_rejected(client: TestClient) -> None:
    payload = order_payload(fresh_key())
    payload["items"] = []

    response = client.post("/orders", json=payload, headers=auth_header())

    assert response.status_code == 422


def test_a_non_positive_quantity_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/orders", json=order_payload(fresh_key(), qty=0), headers=auth_header()
    )

    assert response.status_code == 422
