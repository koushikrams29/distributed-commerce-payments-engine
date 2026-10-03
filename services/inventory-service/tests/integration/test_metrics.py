"""Reservation metrics: one count per order request, settlements counted per row."""

import uuid

from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from sqlalchemy.orm import Session, sessionmaker

from tests.helpers import auth_header, reserve_payload, seed_product


def _requests(result: str) -> float:
    return REGISTRY.get_sample_value(
        "inventory_reservation_requests_total", {"result": result}
    ) or 0.0


def _settled(outcome: str) -> float:
    return REGISTRY.get_sample_value(
        "inventory_reservations_settled_total", {"outcome": outcome}
    ) or 0.0


def _reserve(client: TestClient, product_id: uuid.UUID, qty: int, order_id: uuid.UUID) -> int:
    return client.post(
        "/reservations",
        json=reserve_payload(product_id=product_id, qty=qty, order_id=order_id),
        headers=auth_header(),
    ).status_code


def test_reservation_requests_are_counted_by_result(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    product = seed_product(session_factory, stock_qty=2)
    before = {result: _requests(result) for result in
              ("reserved", "replayed", "insufficient_stock", "product_not_found")}
    order_id = uuid.uuid4()

    assert _reserve(client, product.id, 2, order_id) == 201
    assert _reserve(client, product.id, 2, order_id) == 201
    assert _reserve(client, product.id, 1, uuid.uuid4()) == 409
    assert _reserve(client, uuid.uuid4(), 1, uuid.uuid4()) == 404

    for result, value in before.items():
        assert _requests(result) == value + 1, result


def test_settlements_count_rows_that_changed(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    product = seed_product(session_factory, stock_qty=5)
    paid, cancelled = uuid.uuid4(), uuid.uuid4()
    _reserve(client, product.id, 1, paid)
    _reserve(client, product.id, 1, cancelled)
    committed, released = _settled("committed"), _settled("released")

    for _ in range(2):
        client.post(f"/reservations/{paid}/commit", headers=auth_header())
        client.post(f"/reservations/{cancelled}/release", headers=auth_header())

    assert _settled("committed") == committed + 1
    assert _settled("released") == released + 1


def test_metrics_endpoint_uses_route_templates(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    product = seed_product(session_factory, stock_qty=1)
    order_id = uuid.uuid4()
    _reserve(client, product.id, 1, order_id)
    client.post(f"/reservations/{order_id}/commit", headers=auth_header())

    body = client.get("/metrics").text

    assert "inventory_reservation_requests_total" in body
    assert (
        'http_requests_total{method="POST",route="/reservations/{order_id}/commit",status="200"}'
        in body
    )
    assert str(order_id) not in body
