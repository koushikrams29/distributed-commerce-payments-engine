import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session, selectinload

from app.models import LedgerEntry, Payment


class PaymentRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, payment: Payment) -> Payment:
        self.db.add(payment)
        self.db.flush()
        return payment

    def add_ledger_entry(self, entry: LedgerEntry) -> LedgerEntry:
        self.db.add(entry)
        self.db.flush()
        return entry

    def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        stmt = (
            select(Payment)
            .where(Payment.idempotency_key == idempotency_key)
            .options(selectinload(Payment.ledger_entries))
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_for_order_for_update(self, order_id: uuid.UUID) -> list[Payment]:
        stmt = (
            select(Payment)
            .where(Payment.order_id == order_id)
            .with_for_update()
            .options(selectinload(Payment.ledger_entries))
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_payments(
        self,
        *,
        limit: int,
        status: str | None = None,
        after: tuple[datetime, uuid.UUID] | None = None,
    ) -> list[Payment]:
        """Newest first. Fetch limit+1 so the service can detect a next page."""
        stmt = (
            select(Payment)
            .options(selectinload(Payment.ledger_entries))
            .order_by(Payment.created_at.desc(), Payment.id.desc())
            .limit(limit + 1)
        )
        if status is not None:
            stmt = stmt.where(Payment.status == status)
        if after is not None:
            created_at, payment_id = after
            stmt = stmt.where(
                tuple_(Payment.created_at, Payment.id) < tuple_(created_at, payment_id)
            )
        return list(self.db.execute(stmt).scalars().all())

    def count_by_status(self) -> dict[str, int]:
        stmt = select(Payment.status, func.count()).group_by(Payment.status)
        return {status: count for status, count in self.db.execute(stmt).all()}

    def ledger_totals(self) -> dict[str, Decimal]:
        stmt = select(LedgerEntry.direction, func.sum(LedgerEntry.amount)).group_by(
            LedgerEntry.direction
        )
        return {direction: total for direction, total in self.db.execute(stmt).all()}

    def get_by_order_id(self, order_id: uuid.UUID) -> Payment | None:
        stmt = (
            select(Payment)
            .where(Payment.order_id == order_id)
            .options(selectinload(Payment.ledger_entries))
            .order_by(Payment.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()
