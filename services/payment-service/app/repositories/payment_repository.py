import uuid

from sqlalchemy import select
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

    def get_by_idempotency_key_for_update(
        self, idempotency_key: str
    ) -> Payment | None:
        stmt = (
            select(Payment)
            .where(Payment.idempotency_key == idempotency_key)
            .with_for_update()
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

    def get_by_order_id(self, order_id: uuid.UUID) -> Payment | None:
        stmt = (
            select(Payment)
            .where(Payment.order_id == order_id)
            .options(selectinload(Payment.ledger_entries))
            .order_by(Payment.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalar_one_or_none()
