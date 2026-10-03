"""Tracing through the outbox, and the order metrics Prometheus scrapes."""

import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from opentelemetry import trace
from prometheus_client import REGISTRY
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.events import outbox_relay
from app.models import Order, OrderStatus
from app.schemas.order import OrderCreate, OrderItemCreate
from app.services.order_service import OrderService
from tests.conftest import FakeInventoryClient, FakePaymentClient
from tests.helpers import auth_header, fresh_key, order_payload

tracer = trace.get_tracer(__name__)


def _transitions(previous: str, current: str) -> float:
    return REGISTRY.get_sample_value(
        "order_status_transitions_total", {"from_status": previous, "to_status": current}
    ) or 0.0


def _create_with_event_bus(
    session_factory: sessionmaker[Session],
    fake_inventory: FakeInventoryClient,
    fake_payment: FakePaymentClient,
) -> Order:
    payload = OrderCreate(
        idempotency_key=fresh_key(),
        items=[OrderItemCreate(product_id=uuid.uuid4(), qty=1)],
    )
    db = session_factory()
    try:
        with patch("app.services.order_service.settings.use_event_bus", True):
            order, _ = OrderService(db, inventory=fake_inventory, payment=fake_payment).create_order(
                payload, user_id=uuid.uuid4(), access_token="token"
            )
        return order
    finally:
        db.close()


def test_outbox_rows_remember_the_trace_that_wrote_them(
    session_factory: sessionmaker[Session],
    fake_inventory: FakeInventoryClient,
    fake_payment: FakePaymentClient,
    engine: Engine,
) -> None:
    with tracer.start_as_current_span("POST /orders") as request:
        order = _create_with_event_bus(session_factory, fake_inventory, fake_payment)

    with engine.connect() as connection:
        contexts = connection.execute(
            text("SELECT trace_context FROM outbox WHERE aggregate_id = :id"),
            {"id": order.id},
        ).scalars().all()

    trace_id = format(request.get_span_context().trace_id, "032x")
    assert len(contexts) == 2
    assert all(context["traceparent"].split("-")[1] == trace_id for context in contexts)


def test_outbox_rows_written_outside_a_trace_have_no_context(
    session_factory: sessionmaker[Session],
    fake_inventory: FakeInventoryClient,
    fake_payment: FakePaymentClient,
    engine: Engine,
) -> None:
    order = _create_with_event_bus(session_factory, fake_inventory, fake_payment)

    with engine.connect() as connection:
        contexts = connection.execute(
            text("SELECT trace_context FROM outbox WHERE aggregate_id = :id"),
            {"id": order.id},
        ).scalars().all()

    assert contexts and all(context is None for context in contexts)


def test_the_relay_publishes_with_the_saved_trace_context(
    session_factory: sessionmaker[Session],
    fake_inventory: FakeInventoryClient,
    fake_payment: FakePaymentClient,
    engine: Engine,
) -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE outbox SET published_at = now() WHERE published_at IS NULL"))
    with tracer.start_as_current_span("POST /orders") as request:
        order = _create_with_event_bus(session_factory, fake_inventory, fake_payment)
    lag_count_before = REGISTRY.get_sample_value("outbox_publish_lag_seconds_count") or 0.0

    with patch.object(outbox_relay, "publish_event") as publish:
        relayed = outbox_relay._relay_once()

    assert relayed == 2
    trace_id = format(request.get_span_context().trace_id, "032x")
    for call in publish.call_args_list:
        assert call.kwargs["trace_context"]["traceparent"].split("-")[1] == trace_id
        assert call.args[2]["order_id"] == str(order.id)
    assert REGISTRY.get_sample_value("outbox_publish_lag_seconds_count") == lag_count_before + 2


def test_each_committed_transition_is_counted_once(client: TestClient) -> None:
    before = {
        step: _transitions(*step)
        for step in [("none", "pending"), ("pending", "reserved"), ("reserved", "paid"), ("paid", "fulfilled")]
    }

    # The HTTP fallback runs reserve → charge → fulfil after the response.
    response = client.post("/orders", json=order_payload(fresh_key()), headers=auth_header())
    assert response.status_code == 201

    for step, value in before.items():
        assert _transitions(*step) == value + 1, step


def test_a_replayed_order_is_not_counted_again(client: TestClient) -> None:
    payload = order_payload(fresh_key())
    headers = auth_header()
    client.post("/orders", json=payload, headers=headers)
    before = _transitions("none", "pending")

    replay = client.post("/orders", json=payload, headers=headers)

    assert replay.status_code == 200
    assert _transitions("none", "pending") == before


def test_a_rolled_back_transition_is_not_counted(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    created = client.post("/orders", json=order_payload(fresh_key()), headers=auth_header()).json()
    before = _transitions("fulfilled", "cancelled")

    db = session_factory()
    try:
        order = db.get(Order, uuid.UUID(created["id"]))
        assert order is not None
        order.status = OrderStatus.CANCELLED.value
        db.flush()
        db.rollback()
    finally:
        db.close()

    assert _transitions("fulfilled", "cancelled") == before


def test_metrics_endpoint_exposes_order_metrics(client: TestClient) -> None:
    client.post("/orders", json=order_payload(fresh_key()), headers=auth_header())

    body = client.get("/metrics").text

    assert "order_status_transitions_total" in body
    assert 'http_requests_total{method="POST",route="/orders",status="201"}' in body
