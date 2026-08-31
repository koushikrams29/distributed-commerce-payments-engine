import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from commerce_common.auth import Role
from tests.helpers import auth_header


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_charge_succeeds_and_writes_ledger(
    client: TestClient, engine: Engine
) -> None:
    order_id = uuid.uuid4()
    response = client.post(
        "/charges",
        json={
            "order_id": str(order_id),
            "amount": "150.00",
            "idempotency_key": "charge-key-1",
        },
        headers=auth_header(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["order_id"] == str(order_id)
    assert body["status"] == "succeeded"
    assert body["amount"] == "150.00"
    assert len(body["ledger_entries"]) == 1
    assert body["ledger_entries"][0]["direction"] == "debit"
    assert body["ledger_entries"][0]["amount"] == "150.00"

    with engine.connect() as connection:
        payment_count = connection.execute(
            text("SELECT COUNT(*) FROM payments WHERE order_id = :id"),
            {"id": order_id},
        ).scalar_one()
        assert payment_count == 1


def test_charge_is_idempotent(client: TestClient) -> None:
    payload = {
        "order_id": str(uuid.uuid4()),
        "amount": "50.00",
        "idempotency_key": "same-key",
    }

    first = client.post("/charges", json=payload, headers=auth_header())
    second = client.post("/charges", json=payload, headers=auth_header())

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["payment_id"] == second.json()["payment_id"]


def test_admin_can_read_payment_by_order(client: TestClient) -> None:
    order_id = uuid.uuid4()
    client.post(
        "/charges",
        json={
            "order_id": str(order_id),
            "amount": "25.00",
            "idempotency_key": "lookup-key",
        },
        headers=auth_header(),
    )

    response = client.get(f"/payments/{order_id}", headers=auth_header())
    assert response.status_code == 200
    assert response.json()["order_id"] == str(order_id)
    assert response.json()["status"] == "succeeded"


def test_shopper_cannot_read_payment(client: TestClient) -> None:
    order_id = uuid.uuid4()
    client.post(
        "/charges",
        json={
            "order_id": str(order_id),
            "amount": "25.00",
            "idempotency_key": "rbac-key",
        },
        headers=auth_header(role=Role.ADMIN),
    )

    response = client.get(
        f"/payments/{order_id}",
        headers=auth_header(role=Role.SHOPPER),
    )
    assert response.status_code == 403


def test_charge_fails_when_mock_gateway_declines(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MOCK_PAYMENT_OUTCOME", "failure")
    from app.core import config as config_module

    config_module.settings = config_module.Settings()

    response = client.post(
        "/charges",
        json={
            "order_id": str(uuid.uuid4()),
            "amount": "99.00",
            "idempotency_key": "declined-key",
        },
        headers=auth_header(),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert body["ledger_entries"] == []
