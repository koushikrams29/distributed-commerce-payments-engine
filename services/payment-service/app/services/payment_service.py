import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from commerce_common.pagination import decode_cursor, encode_cursor

from app.core.config import settings
from app.core.metrics import (
    PAYMENT_ATTEMPTS,
    PAYMENT_CAPTURED_AMOUNT,
    PAYMENT_REFUNDS,
    PAYMENT_REPLAYS,
)
from app.gateway.mock import (
    GatewayResult,
    GatewayStatus,
    GatewayTimeoutError,
    MockPaymentGateway,
)
from app.models import LedgerDirection, LedgerEntry, Payment, PaymentStatus
from app.repositories.payment_repository import PaymentRepository
from app.schemas.payment import PaymentListResponse, PaymentRead, PaymentSummary


class IdempotencyKeyReusedError(Exception):
    """The key already belongs to a charge for a different order or amount."""


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
        context: dict | None = None,
    ) -> tuple[Payment, bool]:
        """Attempt a charge once per idempotency key (FR-3).

        Returns (payment, created). Replays return the stored payment with
        created=False; a key reused for a different charge raises
        IdempotencyKeyReusedError rather than reporting someone else's payment.
        """
        existing = self.repository.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return self._replay(existing, order_id=order_id, amount=amount), False

        payment = Payment(
            order_id=order_id,
            idempotency_key=idempotency_key,
            amount=amount,
            status=PaymentStatus.PENDING.value,
            context_json=context,
        )

        try:
            self.repository.add(payment)
            # Commit the idempotency claim before external I/O. If the process
            # dies after the provider sees the request, a retry finds this row
            # and never submits a second charge.
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.repository.get_by_idempotency_key(idempotency_key)
            if existing is None:
                raise
            return self._replay(existing, order_id=order_id, amount=amount), False

        self.db.refresh(payment)
        try:
            result = self.gateway.charge(
                amount, idempotency_key=idempotency_key
            )
        except GatewayTimeoutError as exc:
            payment = self._set_unknown(payment.id, error=str(exc))
        else:
            payment = self._apply_gateway_result(payment.id, result)

        PAYMENT_ATTEMPTS.labels(payment.status).inc()
        return payment, True

    def _set_unknown(self, payment_id: uuid.UUID, *, error: str) -> Payment:
        payment = self.repository.get_by_id_for_update(payment_id)
        if payment is None:
            raise RuntimeError(f"payment disappeared during charge: {payment_id}")
        if payment.status == PaymentStatus.PENDING.value:
            payment.status = PaymentStatus.UNKNOWN.value
            payment.last_error = error[:500]
            self.db.commit()
            self.db.refresh(payment)
        return payment

    def _apply_gateway_result(
        self, payment_id: uuid.UUID, result: GatewayResult
    ) -> Payment:
        payment = self.repository.get_by_id_for_update(payment_id)
        if payment is None:
            raise RuntimeError(f"payment disappeared during charge: {payment_id}")
        if payment.status not in {
            PaymentStatus.PENDING.value,
            PaymentStatus.UNKNOWN.value,
        }:
            return payment

        payment.gateway_reference = result.reference
        payment.last_error = None
        captured = False
        if result.status == GatewayStatus.SUCCEEDED:
            payment.status = PaymentStatus.SUCCEEDED.value
            if not any(
                entry.direction == LedgerDirection.DEBIT.value
                for entry in payment.ledger_entries
            ):
                self.repository.add_ledger_entry(
                    LedgerEntry(
                        payment_id=payment.id,
                        direction=LedgerDirection.DEBIT.value,
                        amount=payment.amount,
                    )
                )
                captured = True
        else:
            payment.status = PaymentStatus.FAILED.value
        self.db.commit()
        if captured:
            PAYMENT_CAPTURED_AMOUNT.inc(float(payment.amount))
        self.db.refresh(payment)
        return payment

    @staticmethod
    def _replay(existing: Payment, *, order_id: uuid.UUID, amount: Decimal) -> Payment:
        if existing.order_id != order_id or existing.amount != amount:
            raise IdempotencyKeyReusedError(
                "idempotency key already used for a different charge"
            )
        PAYMENT_REPLAYS.inc()
        return existing

    def refund_for_order(self, order_id: uuid.UUID) -> list[Payment]:
        """Refund every successful charge for an order; returns the ones refunded now.

        Rows are locked so two deliveries of the same refund request cannot
        both see `succeeded` and credit the customer twice.
        """
        refunded: list[Payment] = []
        for payment in self.repository.list_for_order_for_update(order_id):
            if payment.status != PaymentStatus.SUCCEEDED.value:
                continue
            self.gateway.refund(payment.amount)
            payment.status = PaymentStatus.REFUNDED.value
            self.repository.add_ledger_entry(
                LedgerEntry(
                    payment_id=payment.id,
                    direction=LedgerDirection.CREDIT.value,
                    amount=payment.amount,
                )
            )
            refunded.append(payment)
        self.db.commit()
        PAYMENT_REFUNDS.inc(len(refunded))
        return refunded

    def reconcile_unresolved(self) -> list[Payment]:
        """Resolve stale attempts by provider lookup, never by charging again.

        The returned terminal rows still need their saga outcome reported. Rows
        remain eligible until the publisher marks them, so a crash cannot strand
        a paid order merely because its first reply event was lost.
        """
        cutoff = datetime.now(UTC) - timedelta(
            seconds=settings.payment_reconcile_after_seconds
        )
        candidates = self.repository.list_reconcilable(unresolved_before=cutoff)
        reportable: dict[uuid.UUID, Payment] = {}
        for candidate in candidates:
            if candidate.status in {
                PaymentStatus.PENDING.value,
                PaymentStatus.UNKNOWN.value,
            }:
                result = self.gateway.lookup(
                    idempotency_key=candidate.idempotency_key
                )
                if result is None:
                    if candidate.status == PaymentStatus.PENDING.value:
                        candidate = self._set_unknown(
                            candidate.id,
                            error="provider lookup could not determine the outcome",
                        )
                    continue
                candidate = self._apply_gateway_result(candidate.id, result)
            if (
                candidate.status
                in {PaymentStatus.SUCCEEDED.value, PaymentStatus.FAILED.value}
                and candidate.outcome_reported_at is None
            ):
                reportable[candidate.id] = candidate
        return list(reportable.values())

    def mark_outcome_reported(self, payment_id: uuid.UUID) -> None:
        payment = self.repository.get_by_id_for_update(payment_id)
        if payment is None or payment.outcome_reported_at is not None:
            self.db.rollback()
            return
        if payment.status not in {
            PaymentStatus.SUCCEEDED.value,
            PaymentStatus.FAILED.value,
        }:
            self.db.rollback()
            return
        payment.outcome_reported_at = datetime.now(UTC)
        self.db.commit()

    def get_payment_for_order(self, order_id: uuid.UUID) -> Payment | None:
        return self.repository.get_by_order_id(order_id)

    def list_payments(
        self, *, limit: int = 20, status: str | None = None, cursor: str | None = None
    ) -> PaymentListResponse:
        """Newest first. Raises CursorError for a malformed cursor."""
        after = decode_cursor(cursor) if cursor else None
        rows = self.repository.list_payments(limit=limit, status=status, after=after)
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id)
        return PaymentListResponse(
            items=[PaymentRead.from_payment(payment) for payment in rows],
            next_cursor=next_cursor,
        )

    def summary(self) -> PaymentSummary:
        counts = self.repository.count_by_status()
        totals = self.repository.ledger_totals()
        captured = totals.get(LedgerDirection.DEBIT.value, Decimal("0"))
        refunded = totals.get(LedgerDirection.CREDIT.value, Decimal("0"))
        return PaymentSummary(
            counts={status.value: counts.get(status.value, 0) for status in PaymentStatus},
            total=sum(counts.values()),
            captured_amount=captured,
            refunded_amount=refunded,
            net_amount=captured - refunded,
            generated_at=datetime.now(UTC),
        )
