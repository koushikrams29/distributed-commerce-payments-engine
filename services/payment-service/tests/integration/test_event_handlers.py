"""The saga steps Payment performs when charge and refund requests arrive over RabbitMQ.

Handlers run against the real database; publishing is recorded instead of
sent, so each test asserts both the money outcome and the event it produced.
"""

import uuid
from typing import Any

import pytest
from commerce_common.events import EventType
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core import config
from app.events import consumers
from app.models import Payment, PaymentStatus

Published = list[tuple[str, dict[str, Any]]]


@pytest.fixture
def published(
    monkeypatch: pytest.MonkeyPatch, session_factory: sessionmaker[Session]
) -> Published:
    events: Published = []

    def record(_url: str, routing_key: str, payload: dict[str, Any], **_: Any) -> None:
        events.append((routing_key, payload))

    monkeypatch.setattr(consumers, "SessionLocal", session_factory)
    monkeypatch.setattr(consumers, "publish_event", record)
    # A developer's .env may set the mock gateway to fail; these tests choose per case.
    monkeypatch.setattr(config.settings, "mock_payment_outcome", "success")
    return events


def _charge_requested(order_id: uuid.UUID, **extra: Any) -> dict[str, Any]:
    return {
        "order_id": str(order_id),
        "amount": "25.00",
        "idempotency_key": f"charge-{uuid.uuid4().hex}",
        **extra,
    }


def _payments(session_factory: sessionmaker[Session], order_id: uuid.UUID) -> list[Payment]:
    with session_factory() as db:
        return list(db.scalars(select(Payment).where(Payment.order_id == order_id)))


def test_successful_charge_reports_succeeded_and_passes_items_on(
    published: Published, session_factory: sessionmaker[Session]
) -> None:
    order_id = uuid.uuid4()
    items = [{"product_id": str(uuid.uuid4()), "qty": 1}]

    consumers._dispatch(EventType.CHARGE_REQUESTED, _charge_requested(order_id, items=items))

    [payment] = _payments(session_factory, order_id)
    assert payment.status == PaymentStatus.SUCCEEDED.value
    # Recommendation Service builds co-purchase stats from these items.
    assert published == [
        (
            EventType.PAYMENT_SUCCEEDED,
            {
                "order_id": str(order_id),
                "payment_id": str(payment.id),
                "amount": "25.00",
                "items": items,
            },
        )
    ]


def test_declined_charge_reports_failed(
    published: Published,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config.settings, "mock_payment_outcome", "failure")
    order_id = uuid.uuid4()

    consumers._dispatch(EventType.CHARGE_REQUESTED, _charge_requested(order_id))

    [payment] = _payments(session_factory, order_id)
    assert payment.status == PaymentStatus.FAILED.value
    assert published == [
        (
            EventType.PAYMENT_FAILED,
            {"order_id": str(order_id), "payment_id": str(payment.id), "amount": "25.00"},
        )
    ]


def test_ambiguous_charge_waits_for_reconciliation_instead_of_failing_order(
    published: Published,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config.settings, "mock_payment_outcome", "timeout")
    order_id = uuid.uuid4()

    consumers._dispatch(EventType.CHARGE_REQUESTED, _charge_requested(order_id))

    [payment] = _payments(session_factory, order_id)
    assert payment.status == PaymentStatus.UNKNOWN.value
    assert published == []


def test_redelivered_charge_request_charges_once_but_reports_again(
    published: Published, session_factory: sessionmaker[Session]
) -> None:
    order_id = uuid.uuid4()
    request = _charge_requested(order_id)

    consumers._dispatch(EventType.CHARGE_REQUESTED, request)
    consumers._dispatch(EventType.CHARGE_REQUESTED, request)

    [payment] = _payments(session_factory, order_id)
    # The first outcome may never have reached the order, so it is sent again.
    assert [routing_key for routing_key, _ in published] == [EventType.PAYMENT_SUCCEEDED] * 2
    assert {payload["payment_id"] for _, payload in published} == {str(payment.id)}


def test_key_reused_by_another_order_fails_that_order(
    published: Published, session_factory: sessionmaker[Session]
) -> None:
    first_order, second_order = uuid.uuid4(), uuid.uuid4()
    request = _charge_requested(first_order)
    consumers._dispatch(EventType.CHARGE_REQUESTED, request)
    published.clear()

    consumers._dispatch(
        EventType.CHARGE_REQUESTED, dict(request, order_id=str(second_order))
    )

    assert _payments(session_factory, second_order) == []
    [(routing_key, payload)] = published
    assert routing_key == EventType.PAYMENT_FAILED
    assert payload["order_id"] == str(second_order)
    assert "different charge" in payload["reason"]


def test_refund_request_refunds_once_and_reports_each_refund(
    published: Published, session_factory: sessionmaker[Session]
) -> None:
    order_id = uuid.uuid4()
    consumers._dispatch(EventType.CHARGE_REQUESTED, _charge_requested(order_id))
    published.clear()

    consumers._dispatch(EventType.REFUND_REQUESTED, {"order_id": str(order_id)})
    consumers._dispatch(EventType.REFUND_REQUESTED, {"order_id": str(order_id)})

    [payment] = _payments(session_factory, order_id)
    assert payment.status == PaymentStatus.REFUNDED.value
    assert published == [
        (
            EventType.PAYMENT_REFUNDED,
            {"order_id": str(order_id), "payment_id": str(payment.id), "amount": "25.00"},
        )
    ]


def test_unknown_events_are_ignored(published: Published) -> None:
    consumers._dispatch("payment.renamed", {"order_id": str(uuid.uuid4())})

    assert published == []
