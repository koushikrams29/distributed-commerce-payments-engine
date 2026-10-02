import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.gateway.mock import MockPaymentGateway
from app.services.payment_service import PaymentService


def _charge(
    session_factory: sessionmaker[Session], *, outcome: str = "success"
) -> uuid.UUID:
    order_id = uuid.uuid4()
    db = session_factory()
    try:
        PaymentService(db, gateway=MockPaymentGateway(outcome)).charge(
            order_id=order_id,
            amount=Decimal("80.00"),
            idempotency_key=f"refund-{order_id}",
        )
    finally:
        db.close()
    return order_id


def _refund(session_factory: sessionmaker[Session], order_id: uuid.UUID) -> int:
    db = session_factory()
    try:
        return len(PaymentService(db).refund_for_order(order_id))
    finally:
        db.close()


def _ledger(engine: Engine, order_id: uuid.UUID) -> list[tuple[str, Decimal]]:
    with engine.connect() as connection:
        return [
            (row.direction, row.amount)
            for row in connection.execute(
                text(
                    "SELECT l.direction, l.amount FROM ledger_entries l "
                    "JOIN payments p ON p.id = l.payment_id "
                    "WHERE p.order_id = :id ORDER BY l.created_at, l.direction DESC"
                ),
                {"id": order_id},
            )
        ]


def _status(engine: Engine, order_id: uuid.UUID) -> str:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT status FROM payments WHERE order_id = :id"),
            {"id": order_id},
        ).scalar_one()


def test_refund_credits_the_ledger_and_marks_payment_refunded(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    order_id = _charge(session_factory)

    assert _refund(session_factory, order_id) == 1

    assert _status(engine, order_id) == "refunded"
    assert sorted(_ledger(engine, order_id)) == [
        ("credit", Decimal("80.00")),
        ("debit", Decimal("80.00")),
    ]


def test_refund_is_idempotent(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    order_id = _charge(session_factory)

    _refund(session_factory, order_id)

    assert _refund(session_factory, order_id) == 0
    assert len(_ledger(engine, order_id)) == 2


def test_failed_charge_is_never_refunded(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    order_id = _charge(session_factory, outcome="failure")

    assert _refund(session_factory, order_id) == 0
    assert _status(engine, order_id) == "failed"
    assert _ledger(engine, order_id) == []


def test_concurrent_refund_requests_credit_only_once(
    session_factory: sessionmaker[Session], engine: Engine
) -> None:
    order_id = _charge(session_factory)
    barrier = threading.Barrier(2)

    def attempt() -> int:
        barrier.wait(timeout=10)
        return _refund(session_factory, order_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result() for f in [pool.submit(attempt), pool.submit(attempt)]]

    assert sorted(results) == [0, 1]
    assert [d for d, _ in _ledger(engine, order_id)].count("credit") == 1
