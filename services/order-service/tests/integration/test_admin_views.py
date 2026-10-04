"""Admin read views: pipeline summary, per-order event history, date filters."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from commerce_common.auth import Role
from commerce_common.events import EventType
from app.schemas.order import OrderCreate, OrderItemCreate
from app.services.order_service import OrderService
from tests.conftest import FakeInventoryClient, FakePaymentClient
from tests.helpers import auth_header

TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def _admin() -> dict[str, str]:
    return auth_header(role=Role.ADMIN)


def _create_order(
    session_factory: sessionmaker[Session],
    fake_inventory: FakeInventoryClient,
    fake_payment: FakePaymentClient,
) -> uuid.UUID:
    """A pending order with its outbox rows, as the event-bus path writes them."""
    payload = OrderCreate(
        idempotency_key=f"admin-view-{uuid.uuid4().hex}",
        items=[OrderItemCreate(product_id=uuid.uuid4(), qty=1)],
    )
    db = session_factory()
    try:
        with patch("app.services.order_service.settings.use_event_bus", True):
            order, _ = OrderService(
                db, inventory=fake_inventory, payment=fake_payment
            ).create_order(payload, user_id=uuid.uuid4(), access_token="token")
        return order.id
    finally:
        db.close()


def _set(engine: Engine, sql: str, **params: object) -> None:
    with engine.begin() as connection:
        connection.execute(text(sql), params)


class TestSummary:
    def test_counts_every_status_including_empty_ones(
        self,
        client: TestClient,
        engine: Engine,
        session_factory: sessionmaker[Session],
        fake_inventory: FakeInventoryClient,
        fake_payment: FakePaymentClient,
    ) -> None:
        pending = _create_order(session_factory, fake_inventory, fake_payment)
        cancelled = _create_order(session_factory, fake_inventory, fake_payment)
        _set(engine, "UPDATE orders SET status = 'cancelled' WHERE id = :id", id=cancelled)

        body = client.get("/orders/summary", headers=_admin()).json()

        assert body["counts"] == {
            "pending": 1,
            "reserved": 0,
            "paid": 0,
            "fulfilled": 0,
            "cancelled": 1,
        }
        assert body["total"] == 2
        assert pending != cancelled

    def test_reports_the_unpublished_outbox_backlog(
        self,
        client: TestClient,
        engine: Engine,
        session_factory: sessionmaker[Session],
        fake_inventory: FakeInventoryClient,
        fake_payment: FakePaymentClient,
    ) -> None:
        order_id = _create_order(session_factory, fake_inventory, fake_payment)
        oldest = datetime.now(UTC) - timedelta(minutes=5)
        _set(
            engine,
            "UPDATE outbox SET created_at = :oldest WHERE aggregate_id = :id"
            " AND event_type = :created",
            oldest=oldest,
            id=order_id,
            created=EventType.ORDER_CREATED,
        )
        _set(
            engine,
            "UPDATE outbox SET published_at = now() WHERE aggregate_id = :id"
            " AND event_type = :changed",
            id=order_id,
            changed=EventType.ORDER_STATUS_CHANGED,
        )

        outbox = client.get("/orders/summary", headers=_admin()).json()["outbox"]

        assert outbox["unpublished"] == 1
        assert datetime.fromisoformat(outbox["oldest_unpublished_at"]) == oldest

    def test_an_empty_outbox_has_no_oldest_row(self, client: TestClient, engine: Engine) -> None:
        outbox = client.get("/orders/summary", headers=_admin()).json()["outbox"]

        assert outbox == {"unpublished": 0, "oldest_unpublished_at": None}

    def test_counts_orders_past_the_reconciler_timeout(
        self,
        client: TestClient,
        engine: Engine,
        session_factory: sessionmaker[Session],
        fake_inventory: FakeInventoryClient,
        fake_payment: FakePaymentClient,
    ) -> None:
        stale = datetime.now(UTC) - timedelta(hours=2)
        stuck_pending = _create_order(session_factory, fake_inventory, fake_payment)
        _create_order(session_factory, fake_inventory, fake_payment)  # recent: not overdue
        stuck_paid = _create_order(session_factory, fake_inventory, fake_payment)
        _set(engine, "UPDATE orders SET created_at = :t WHERE id = :id", t=stale, id=stuck_pending)
        _set(
            engine,
            "UPDATE orders SET status = 'paid', updated_at = :t WHERE id = :id",
            t=stale,
            id=stuck_paid,
        )

        body = client.get("/orders/summary", headers=_admin()).json()

        overdue = {row["status"]: row for row in body["overdue"]}
        assert overdue["pending"]["count"] == 1
        assert overdue["reserved"]["count"] == 0
        assert overdue["paid"]["count"] == 1
        assert overdue["pending"]["after_minutes"] == 30
        assert body["reconciler_enabled"] is False

    def test_is_admin_only(self, client: TestClient, engine: Engine) -> None:
        response = client.get("/orders/summary", headers=auth_header(role=Role.SHOPPER))

        assert response.status_code == 403


class TestOrderEvents:
    def test_lists_the_order_history_oldest_first(
        self,
        client: TestClient,
        session_factory: sessionmaker[Session],
        fake_inventory: FakeInventoryClient,
        fake_payment: FakePaymentClient,
    ) -> None:
        order_id = _create_order(session_factory, fake_inventory, fake_payment)
        db = session_factory()
        try:
            with patch("app.services.order_service.settings.use_event_bus", True):
                OrderService(db).on_inventory_reserved(order_id)
        finally:
            db.close()

        events = client.get(f"/orders/{order_id}/events", headers=_admin()).json()

        types = [event["event_type"] for event in events]
        assert set(types[:2]) == {EventType.ORDER_CREATED, EventType.ORDER_STATUS_CHANGED}
        assert set(types[2:]) == {EventType.ORDER_STATUS_CHANGED, EventType.CHARGE_REQUESTED}
        changes = [
            (event["payload"]["previous_status"], event["payload"]["status"])
            for event in events
            if event["event_type"] == EventType.ORDER_STATUS_CHANGED
        ]
        assert changes == [(None, "pending"), ("pending", "reserved")]
        assert all(event["published_at"] is None for event in events)

    def test_exposes_the_trace_id_of_the_writing_request(
        self,
        client: TestClient,
        engine: Engine,
        session_factory: sessionmaker[Session],
        fake_inventory: FakeInventoryClient,
        fake_payment: FakePaymentClient,
    ) -> None:
        order_id = _create_order(session_factory, fake_inventory, fake_payment)
        _set(
            engine,
            "UPDATE outbox SET trace_context = CAST(:ctx AS jsonb) WHERE aggregate_id = :id",
            ctx=f'{{"traceparent": "{TRACEPARENT}"}}',
            id=order_id,
        )

        events = client.get(f"/orders/{order_id}/events", headers=_admin()).json()

        assert {event["trace_id"] for event in events} == {TRACE_ID}

    def test_unknown_order_returns_404(self, client: TestClient, engine: Engine) -> None:
        response = client.get(f"/orders/{uuid.uuid4()}/events", headers=_admin())

        assert response.status_code == 404

    def test_is_admin_only(
        self,
        client: TestClient,
        session_factory: sessionmaker[Session],
        fake_inventory: FakeInventoryClient,
        fake_payment: FakePaymentClient,
    ) -> None:
        order_id = _create_order(session_factory, fake_inventory, fake_payment)

        response = client.get(
            f"/orders/{order_id}/events", headers=auth_header(role=Role.SHOPPER)
        )

        assert response.status_code == 403


class TestDateFilters:
    def test_limits_the_list_to_the_creation_window(
        self,
        client: TestClient,
        engine: Engine,
        session_factory: sessionmaker[Session],
        fake_inventory: FakeInventoryClient,
        fake_payment: FakePaymentClient,
    ) -> None:
        now = datetime.now(UTC)
        old = _create_order(session_factory, fake_inventory, fake_payment)
        inside = _create_order(session_factory, fake_inventory, fake_payment)
        _set(engine, "UPDATE orders SET created_at = :t WHERE id = :id", t=now - timedelta(days=3), id=old)
        _set(engine, "UPDATE orders SET created_at = :t WHERE id = :id", t=now - timedelta(hours=1), id=inside)

        response = client.get(
            "/orders",
            params={
                "created_from": (now - timedelta(days=1)).isoformat(),
                "created_to": now.isoformat(),
            },
            headers=_admin(),
        )

        assert response.status_code == 200
        assert [order["id"] for order in response.json()["items"]] == [str(inside)]

    @pytest.mark.parametrize("name", ["created_from", "created_to"])
    def test_a_time_without_an_offset_is_rejected(
        self, client: TestClient, engine: Engine, name: str
    ) -> None:
        response = client.get(
            "/orders", params={name: "2026-01-01T00:00:00"}, headers=_admin()
        )

        assert response.status_code == 422
        assert "timezone" in response.json()["detail"]
