import uuid
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.gateway.mock import MockPaymentGateway
from app.models import LedgerDirection, LedgerEntry, Payment, PaymentStatus
from app.repositories.payment_repository import PaymentRepository


class PaymentService:
    def __init__(
        self,
        db: Session,
        gateway: MockPaymentGateway | None = None,
    ):
        self.db = db
        self.repository = PaymentRepository(db)
        self.gateway = gateway or MockPaymentGateway()

    def charge(
        self,
        *,
        order_id: uuid.UUID,
        amount: Decimal,
        idempotency_key: str,
    ) -> tuple[Payment, bool]:
        """Attempt a charge once per idempotency key (FR-3).

        Returns (payment, created). Replays return the stored payment with
        created=False.
        """
        existing = self.repository.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing, False

        payment = Payment(
            order_id=order_id,
            idempotency_key=idempotency_key,
            amount=amount,
            status=PaymentStatus.PENDING.value,
        )

        try:
            self.repository.add(payment)
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            existing = self.repository.get_by_idempotency_key(idempotency_key)
            if existing is None:
                raise
            return existing, False

        if self.gateway.charge(amount):
            payment.status = PaymentStatus.SUCCEEDED.value
            self.repository.add_ledger_entry(
                LedgerEntry(
                    payment_id=payment.id,
                    direction=LedgerDirection.DEBIT.value,
                    amount=amount,
                )
            )
        else:
            payment.status = PaymentStatus.FAILED.value

        self.db.commit()
        self.db.refresh(payment)
        return payment, True

    def get_payment_for_order(self, order_id: uuid.UUID) -> Payment | None:
        return self.repository.get_by_order_id(order_id)
