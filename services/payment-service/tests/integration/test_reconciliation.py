import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.gateway.mock import MockPaymentGateway
from app.models import LedgerDirection, LedgerEntry, Payment, PaymentStatus
from app.services.payment_service import PaymentService


class CountingGateway(MockPaymentGateway):
    def __init__(self, outcome: str, *, timeout_resolution: str = "unknown"):
        super().__init__(outcome, timeout_resolution=timeout_resolution)
        self.charge_calls = 0
        self.lookup_calls = 0

    def charge(self, amount: Decimal, *, idempotency_key: str):
        self.charge_calls += 1
        return super().charge(amount, idempotency_key=idempotency_key)

    def lookup(self, *, idempotency_key: str):
        self.lookup_calls += 1
        return super().lookup(idempotency_key=idempotency_key)


def _age(db: Session, payment_id: uuid.UUID) -> None:
    db.execute(
        update(Payment)
        .where(Payment.id == payment_id)
        .values(updated_at=datetime.now(UTC) - timedelta(minutes=5))
    )
    db.commit()


def test_timeout_is_durable_and_replay_never_charges_again(
    session_factory: sessionmaker[Session],
) -> None:
    order_id = uuid.uuid4()
    key = f"timeout-{uuid.uuid4().hex}"
    gateway = CountingGateway("timeout")

    with session_factory() as db:
        first, created = PaymentService(db, gateway=gateway).charge(
            order_id=order_id,
            amount=Decimal("20.00"),
            idempotency_key=key,
        )
        replay, replay_created = PaymentService(db, gateway=gateway).charge(
            order_id=order_id,
            amount=Decimal("20.00"),
            idempotency_key=key,
        )

    assert created is True
    assert replay_created is False
    assert first.id == replay.id
    assert replay.status == PaymentStatus.UNKNOWN.value
    assert replay.last_error == "mock gateway timed out after submission"
    assert gateway.charge_calls == 1


def test_unknown_success_is_resolved_by_lookup_with_one_ledger_debit(
    session_factory: sessionmaker[Session],
) -> None:
    gateway = CountingGateway("timeout", timeout_resolution="success")
    with session_factory() as db:
        payment, _ = PaymentService(db, gateway=gateway).charge(
            order_id=uuid.uuid4(),
            amount=Decimal("35.00"),
            idempotency_key=f"resolve-{uuid.uuid4().hex}",
        )
        _age(db, payment.id)

        service = PaymentService(db, gateway=gateway)
        [resolved] = service.reconcile_unresolved()
        # Until reporting is acknowledged, another pass may report the outcome
        # again but must never create another financial entry.
        [again] = service.reconcile_unresolved()
        service.mark_outcome_reported(resolved.id)
        assert service.reconcile_unresolved() == []

        debit_count = db.scalar(
            select(func.count())
            .select_from(LedgerEntry)
            .where(
                LedgerEntry.payment_id == payment.id,
                LedgerEntry.direction == LedgerDirection.DEBIT.value,
            )
        )

    assert resolved.status == PaymentStatus.SUCCEEDED.value
    assert again.id == resolved.id
    assert gateway.charge_calls == 1
    assert gateway.lookup_calls == 1
    assert debit_count == 1


def test_unknown_decline_is_resolved_without_moving_money(
    session_factory: sessionmaker[Session],
) -> None:
    gateway = CountingGateway("timeout", timeout_resolution="failure")
    with session_factory() as db:
        payment, _ = PaymentService(db, gateway=gateway).charge(
            order_id=uuid.uuid4(),
            amount=Decimal("15.00"),
            idempotency_key=f"decline-{uuid.uuid4().hex}",
        )
        _age(db, payment.id)

        [resolved] = PaymentService(db, gateway=gateway).reconcile_unresolved()

        ledger_count = db.scalar(
            select(func.count())
            .select_from(LedgerEntry)
            .where(LedgerEntry.payment_id == payment.id)
        )

    assert resolved.status == PaymentStatus.FAILED.value
    assert gateway.charge_calls == 1
    assert gateway.lookup_calls == 1
    assert ledger_count == 0


def test_stale_pending_attempt_is_looked_up_instead_of_charged(
    session_factory: sessionmaker[Session],
) -> None:
    payment = Payment(
        order_id=uuid.uuid4(),
        idempotency_key=f"crashed-{uuid.uuid4().hex}",
        amount=Decimal("12.00"),
        status=PaymentStatus.PENDING.value,
    )
    gateway = CountingGateway("success")
    with session_factory() as db:
        db.add(payment)
        db.commit()
        _age(db, payment.id)

        [resolved] = PaymentService(db, gateway=gateway).reconcile_unresolved()

    assert resolved.status == PaymentStatus.SUCCEEDED.value
    assert gateway.charge_calls == 0
    assert gateway.lookup_calls == 1
