"""Admin read views: the payment list and the ledger summary."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from commerce_common.auth import Role
from app.gateway.mock import MockPaymentGateway
from app.services.payment_service import PaymentService
from tests.helpers import auth_header


def _charge(
    session_factory: sessionmaker[Session],
    *,
    amount: str = "40.00",
    outcome: str = "success",
) -> uuid.UUID:
    order_id = uuid.uuid4()
    db = session_factory()
    try:
        PaymentService(db, gateway=MockPaymentGateway(outcome)).charge(
            order_id=order_id, amount=Decimal(amount), idempotency_key=f"order-{order_id}"
        )
    finally:
        db.close()
    return order_id


def _refund(session_factory: sessionmaker[Session], order_id: uuid.UUID) -> None:
    db = session_factory()
    try:
        PaymentService(db).refund_for_order(order_id)
    finally:
        db.close()


def _age(engine: Engine, order_id: uuid.UUID, minutes: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE payments SET created_at = :t WHERE order_id = :id"),
            {"t": datetime.now(UTC) - timedelta(minutes=minutes), "id": order_id},
        )


class TestPaymentList:
    def test_lists_newest_first_with_ledger_and_key(
        self, client: TestClient, engine: Engine, session_factory: sessionmaker[Session]
    ) -> None:
        older = _charge(session_factory)
        newer = _charge(session_factory, amount="15.50")
        _age(engine, older, minutes=10)

        body = client.get("/payments", headers=auth_header()).json()

        assert [item["order_id"] for item in body["items"]] == [str(newer), str(older)]
        first = body["items"][0]
        assert first["idempotency_key"] == f"order-{newer}"
        assert Decimal(first["amount"]) == Decimal("15.50")
        assert [entry["direction"] for entry in first["ledger_entries"]] == ["debit"]
        assert body["next_cursor"] is None

    def test_pages_through_with_a_cursor(
        self, client: TestClient, engine: Engine, session_factory: sessionmaker[Session]
    ) -> None:
        orders = [_charge(session_factory) for _ in range(3)]
        for minutes, order_id in enumerate(orders):
            _age(engine, order_id, minutes=minutes * 5)

        first = client.get("/payments", params={"limit": 2}, headers=auth_header()).json()
        second = client.get(
            "/payments",
            params={"limit": 2, "cursor": first["next_cursor"]},
            headers=auth_header(),
        ).json()

        seen = [item["order_id"] for item in first["items"] + second["items"]]
        assert seen == [str(order_id) for order_id in orders]
        assert second["next_cursor"] is None

    def test_filters_by_status(
        self, client: TestClient, engine: Engine, session_factory: sessionmaker[Session]
    ) -> None:
        _charge(session_factory)
        declined = _charge(session_factory, outcome="failure")

        body = client.get(
            "/payments", params={"status": "failed"}, headers=auth_header()
        ).json()

        assert [item["order_id"] for item in body["items"]] == [str(declined)]
        assert body["items"][0]["ledger_entries"] == []

    @pytest.mark.parametrize(
        ("params", "detail"),
        [({"status": "lost"}, "status must be one of"), ({"cursor": "%%%"}, "invalid cursor")],
    )
    def test_rejects_bad_parameters(
        self, client: TestClient, engine: Engine, params: dict[str, str], detail: str
    ) -> None:
        response = client.get("/payments", params=params, headers=auth_header())

        assert response.status_code == 422
        assert detail in response.json()["detail"]

    def test_is_admin_only(self, client: TestClient, engine: Engine) -> None:
        response = client.get("/payments", headers=auth_header(role=Role.SHOPPER))

        assert response.status_code == 403


class TestSummary:
    def test_counts_statuses_and_totals_the_ledger(
        self, client: TestClient, engine: Engine, session_factory: sessionmaker[Session]
    ) -> None:
        _charge(session_factory, amount="100.00")
        refunded = _charge(session_factory, amount="30.00")
        _charge(session_factory, amount="999.00", outcome="failure")
        _refund(session_factory, refunded)

        body = client.get("/payments/summary", headers=auth_header()).json()

        assert body["counts"] == {"pending": 0, "succeeded": 1, "failed": 1, "refunded": 1}
        assert body["total"] == 3
        # A declined charge never touches the ledger.
        assert Decimal(body["captured_amount"]) == Decimal("130.00")
        assert Decimal(body["refunded_amount"]) == Decimal("30.00")
        assert Decimal(body["net_amount"]) == Decimal("100.00")

    def test_an_empty_ledger_sums_to_zero(self, client: TestClient, engine: Engine) -> None:
        body = client.get("/payments/summary", headers=auth_header()).json()

        assert body["total"] == 0
        assert Decimal(body["captured_amount"]) == Decimal("0")
        assert Decimal(body["net_amount"]) == Decimal("0")

    def test_is_admin_only(self, client: TestClient, engine: Engine) -> None:
        response = client.get("/payments/summary", headers=auth_header(role=Role.SHOPPER))

        assert response.status_code == 403
