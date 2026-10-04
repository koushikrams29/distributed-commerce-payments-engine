"""The unique constraint on idempotency_key is what makes concurrent charges safe.

Two deliveries can both look the key up, both miss, and both insert. These
tests replay that interleaving: the winner's row already exists, but the
loser's lookup ran before it committed.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.gateway.mock import MockPaymentGateway
from app.models import Payment
from app.repositories.payment_repository import PaymentRepository
from app.services.payment_service import IdempotencyKeyReusedError, PaymentService


def _charge(db: Session, order_id: uuid.UUID, key: str) -> tuple[Payment, bool]:
    return PaymentService(db, gateway=MockPaymentGateway("success")).charge(
        order_id=order_id, amount=Decimal("30.00"), idempotency_key=key
    )


def _lose_the_race(monkeypatch: pytest.MonkeyPatch) -> None:
    real_lookup = PaymentRepository.get_by_idempotency_key
    calls = 0

    def stale_first_lookup(self: PaymentRepository, key: str) -> Payment | None:
        nonlocal calls
        calls += 1
        return None if calls == 1 else real_lookup(self, key)

    monkeypatch.setattr(PaymentRepository, "get_by_idempotency_key", stale_first_lookup)


def test_losing_a_concurrent_insert_returns_the_winners_payment(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    order_id, key = uuid.uuid4(), f"race-{uuid.uuid4().hex}"
    with session_factory() as db:
        winner, _ = _charge(db, order_id, key)
    _lose_the_race(monkeypatch)

    with session_factory() as db:
        loser, created = _charge(db, order_id, key)

    assert not created
    assert loser.id == winner.id
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Payment)) == 1


def test_losing_a_concurrent_insert_to_a_different_charge_is_refused(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    key = f"race-{uuid.uuid4().hex}"
    with session_factory() as db:
        _charge(db, uuid.uuid4(), key)
    _lose_the_race(monkeypatch)

    with session_factory() as db, pytest.raises(IdempotencyKeyReusedError):
        _charge(db, uuid.uuid4(), key)
