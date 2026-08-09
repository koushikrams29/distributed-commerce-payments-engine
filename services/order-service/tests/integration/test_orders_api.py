import uuid
from decimal import Decimal

from fastapi.testclient import TestClient

from app.services.order_service import PLACEHOLDER_UNIT_PRICE
from tests.helpers import fresh_key, order_payload


def test_creating_an_order_returns_201(client: TestClient) -> None:
    response = client.post("/orders", json=order_payload(fresh_key()))

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert Decimal(str(body["total_amount"])) == PLACEHOLDER_UNIT_PRICE * 2
    assert len(body["items"]) == 1


def test_a_created_order_can_be_read_back(client: TestClient) -> None:
    created = client.post("/orders", json=order_payload(fresh_key())).json()

    response = client.get(f"/orders/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_reading_an_unknown_order_returns_404(client: TestClient) -> None:
    response = client.get(f"/orders/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Order not found"


def test_an_order_without_an_idempotency_key_is_rejected(client: TestClient) -> None:
    payload = order_payload(fresh_key())
    del payload["idempotency_key"]

    response = client.post("/orders", json=payload)

    assert response.status_code == 422


def test_an_order_without_items_is_rejected(client: TestClient) -> None:
    payload = order_payload(fresh_key())
    payload["items"] = []

    response = client.post("/orders", json=payload)

    assert response.status_code == 422


def test_a_non_positive_quantity_is_rejected(client: TestClient) -> None:
    response = client.post("/orders", json=order_payload(fresh_key(), qty=0))

    assert response.status_code == 422
