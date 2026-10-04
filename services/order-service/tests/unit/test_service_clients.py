"""How the HTTP fallback (USE_EVENT_BUS=false) maps Inventory and Payment responses.

The order saga decides between cancelling an order and retrying later from
these error types, so each status code must land on the right one.
"""

import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.clients.inventory import (
    InsufficientStockError,
    InventoryClient,
    InventoryUnavailableError,
    ProductNotFoundError,
)
from app.clients.payment import PaymentClient, PaymentUnavailableError

TOKEN = "access-token"


def respond(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    status_code: int,
    body: dict[str, Any] | None = None,
) -> list[httpx.Request]:
    sent: list[httpx.Request] = []

    def fake(url: str, **kwargs: Any) -> httpx.Response:
        request = httpx.Request(method.upper(), url, headers=kwargs.get("headers"))
        sent.append(request)
        return httpx.Response(status_code, json=body or {}, request=request)

    monkeypatch.setattr(httpx, method, fake)
    return sent


def fail_to_connect(monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    def fake(url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=httpx.Request(method.upper(), url))

    monkeypatch.setattr(httpx, method, fake)


def test_product_is_parsed_and_the_token_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    product_id = uuid.uuid4()
    sent = respond(
        monkeypatch,
        "get",
        200,
        {"id": str(product_id), "name": "Widget", "price": "19.99", "stock_qty": 4},
    )

    product = InventoryClient(base_url="http://inventory/").get_product(
        product_id, access_token=TOKEN
    )

    assert product.price == Decimal("19.99")
    assert product.stock_qty == 4
    assert str(sent[0].url) == f"http://inventory/products/{product_id}"
    assert sent[0].headers["Authorization"] == f"Bearer {TOKEN}"


def test_missing_product_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    respond(monkeypatch, "get", 404)

    with pytest.raises(ProductNotFoundError):
        InventoryClient(base_url="http://inventory").get_product(uuid.uuid4(), access_token=TOKEN)


def test_conflict_on_reserve_is_insufficient_stock(monkeypatch: pytest.MonkeyPatch) -> None:
    respond(monkeypatch, "post", 409, {"detail": "only 1 left"})

    with pytest.raises(InsufficientStockError) as raised:
        InventoryClient(base_url="http://inventory").reserve(
            order_id=uuid.uuid4(), items=[], access_token=TOKEN
        )

    assert raised.value.detail == "only 1 left"


@pytest.mark.parametrize("status_code", [401, 500, 503])
def test_other_inventory_errors_are_unavailable(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    respond(monkeypatch, "post", status_code)
    client = InventoryClient(base_url="http://inventory")

    with pytest.raises(InventoryUnavailableError):
        client.reserve(order_id=uuid.uuid4(), items=[], access_token=TOKEN)
    with pytest.raises(InventoryUnavailableError):
        client.commit(order_id=uuid.uuid4(), access_token=TOKEN)
    with pytest.raises(InventoryUnavailableError):
        client.release(order_id=uuid.uuid4(), access_token=TOKEN)


def test_unreachable_inventory_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    fail_to_connect(monkeypatch, "get")
    fail_to_connect(monkeypatch, "post")
    client = InventoryClient(base_url="http://inventory")

    with pytest.raises(InventoryUnavailableError):
        client.get_product(uuid.uuid4(), access_token=TOKEN)
    with pytest.raises(InventoryUnavailableError):
        client.reserve(order_id=uuid.uuid4(), items=[], access_token=TOKEN)
    with pytest.raises(InventoryUnavailableError):
        client.commit(order_id=uuid.uuid4(), access_token=TOKEN)


def test_reservation_actions_hit_the_order_url(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = respond(monkeypatch, "post", 200)
    order_id = uuid.uuid4()
    client = InventoryClient(base_url="http://inventory")

    client.commit(order_id=order_id, access_token=TOKEN)
    client.release(order_id=order_id, access_token=TOKEN)

    assert [str(request.url) for request in sent] == [
        f"http://inventory/reservations/{order_id}/commit",
        f"http://inventory/reservations/{order_id}/release",
    ]


@pytest.mark.parametrize("status_code", [200, 201])
def test_charge_result_is_parsed_for_new_and_replayed_charges(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    order_id, payment_id = uuid.uuid4(), uuid.uuid4()
    respond(
        monkeypatch,
        "post",
        status_code,
        {
            "payment_id": str(payment_id),
            "order_id": str(order_id),
            "status": "succeeded",
            "amount": "42.50",
        },
    )

    result = PaymentClient(base_url="http://payment").charge(
        order_id=order_id, amount=Decimal("42.50"), idempotency_key="key-123", access_token=TOKEN
    )

    assert result.payment_id == payment_id
    assert result.amount == Decimal("42.50")


def test_payment_errors_are_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    client = PaymentClient(base_url="http://payment")
    charge = {
        "order_id": uuid.uuid4(),
        "amount": Decimal("1.00"),
        "idempotency_key": "key-123",
        "access_token": TOKEN,
    }

    respond(monkeypatch, "post", 500)
    with pytest.raises(PaymentUnavailableError):
        client.charge(**charge)

    fail_to_connect(monkeypatch, "post")
    with pytest.raises(PaymentUnavailableError):
        client.charge(**charge)
