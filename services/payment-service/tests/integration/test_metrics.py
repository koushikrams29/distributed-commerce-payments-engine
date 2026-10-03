"""Payment metrics count real attempts only: replays and no-op refunds are not attempts."""

import uuid
from decimal import Decimal

from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from sqlalchemy.orm import Session, sessionmaker

from app.gateway.mock import MockPaymentGateway
from app.services.payment_service import PaymentService
from tests.helpers import auth_header, charge_payload


def _sample(name: str, labels: dict[str, str] | None = None) -> float:
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0


def _charge(
    session_factory: sessionmaker[Session], *, outcome: str, key: str | None = None
) -> uuid.UUID:
    order_id = uuid.uuid4()
    db = session_factory()
    try:
        PaymentService(db, gateway=MockPaymentGateway(outcome)).charge(
            order_id=order_id,
            amount=Decimal("40.00"),
            idempotency_key=key or f"metrics-{order_id}",
        )
    finally:
        db.close()
    return order_id


def test_attempts_are_counted_by_result(session_factory: sessionmaker[Session]) -> None:
    succeeded = _sample("payment_attempts_total", {"result": "succeeded"})
    failed = _sample("payment_attempts_total", {"result": "failed"})
    captured = _sample("payment_captured_amount_total")

    _charge(session_factory, outcome="success")
    _charge(session_factory, outcome="failure")

    assert _sample("payment_attempts_total", {"result": "succeeded"}) == succeeded + 1
    assert _sample("payment_attempts_total", {"result": "failed"}) == failed + 1
    assert _sample("payment_captured_amount_total") == captured + 40.0


def test_a_replayed_charge_is_a_replay_not_an_attempt(
    session_factory: sessionmaker[Session],
) -> None:
    key = f"replay-{uuid.uuid4().hex}"
    _charge(session_factory, outcome="success", key=key)
    attempts = _sample("payment_attempts_total", {"result": "succeeded"})
    replays = _sample("payment_idempotent_replays_total")

    _charge(session_factory, outcome="success", key=key)

    assert _sample("payment_attempts_total", {"result": "succeeded"}) == attempts
    assert _sample("payment_idempotent_replays_total") == replays + 1


def test_only_refunds_that_happen_are_counted(session_factory: sessionmaker[Session]) -> None:
    order_id = _charge(session_factory, outcome="success")
    before = _sample("payment_refunds_total")

    for _ in range(2):
        db = session_factory()
        try:
            PaymentService(db).refund_for_order(order_id)
        finally:
            db.close()

    assert _sample("payment_refunds_total") == before + 1


def test_metrics_endpoint_exposes_payment_metrics(client: TestClient) -> None:
    client.post("/charges", json=charge_payload(), headers=auth_header())

    body = client.get("/metrics").text

    assert "payment_attempts_total" in body
    assert 'http_requests_total{method="POST",route="/charges",status="201"}' in body
