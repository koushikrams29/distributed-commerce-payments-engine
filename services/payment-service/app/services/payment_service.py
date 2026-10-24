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
from app.models import (
    LedgerDirection,
    LedgerEntry,
    Payment,
    PaymentStatus,
    RefundAttempt,
    RefundStatus,
)
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

    def refund_for_order(self, order_id: uuid.UUID) -> list[RefundAttempt]:
        """Submit at most one durable refund operation for each payment."""
        refunded: list[RefundAttempt] = []
        for payment in self.repository.list_for_order_for_update(order_id):
            if payment.status != PaymentStatus.SUCCEEDED.value:
                continue
            if self.repository.get_refund_for_payment(payment.id) is not None:
                continue
            attempt = RefundAttempt(
                payment_id=payment.id,
                idempotency_key=f"refund-{payment.id}",
                status=RefundStatus.PENDING.value,
            )
            try:
                self.repository.add_refund_attempt(attempt)
                # The durable idempotency claim must exist before provider I/O.
                self.db.commit()
            except IntegrityError:
                self.db.rollback()
                continue
            self.db.refresh(attempt)
            try:
                result = self.gateway.refund(
                    payment.amount, idempotency_key=attempt.idempotency_key
                )
            except GatewayTimeoutError as exc:
                self._set_refund_unknown(attempt.id, error=str(exc))
                continue
            attempt = self._apply_refund_result(attempt.id, result)
            if attempt.status == RefundStatus.SUCCEEDED.value:
                refunded.append(attempt)
        return refunded

    def _set_refund_unknown(
        self, attempt_id: uuid.UUID, *, error: str
    ) -> RefundAttempt:
        attempt = self.repository.get_refund_by_id_for_update(attempt_id)
        if attempt is None:
            raise RuntimeError(f"refund attempt disappeared: {attempt_id}")
        if attempt.status == RefundStatus.PENDING.value:
            attempt.status = RefundStatus.UNKNOWN.value
            attempt.last_error = error[:500]
            self.db.commit()
            self.db.refresh(attempt)
        return attempt

    def _apply_refund_result(
        self, attempt_id: uuid.UUID, result: GatewayResult
    ) -> RefundAttempt:
        attempt = self.repository.get_refund_by_id_for_update(attempt_id)
        if attempt is None:
            raise RuntimeError(f"refund attempt disappeared: {attempt_id}")
        if attempt.status not in {
            RefundStatus.PENDING.value,
            RefundStatus.UNKNOWN.value,
        }:
            return attempt

        attempt.gateway_reference = result.reference
        attempt.last_error = None
        credited = False
        if result.status == GatewayStatus.SUCCEEDED:
            attempt.status = RefundStatus.SUCCEEDED.value
            attempt.payment.status = PaymentStatus.REFUNDED.value
            if not any(
                entry.direction == LedgerDirection.CREDIT.value
                for entry in attempt.payment.ledger_entries
            ):
                self.repository.add_ledger_entry(
                    LedgerEntry(
                        payment_id=attempt.payment_id,
                        direction=LedgerDirection.CREDIT.value,
                        amount=attempt.payment.amount,
                    )
                )
                credited = True
        else:
            attempt.status = RefundStatus.FAILED.value
        self.db.commit()
        if credited:
            PAYMENT_REFUNDS.inc()
        self.db.refresh(attempt)
        return attempt

    def reconcile_refunds(self) -> list[RefundAttempt]:
        """Resolve stale refunds by lookup and return unreported successes."""
        cutoff = datetime.now(UTC) - timedelta(
            seconds=settings.payment_reconcile_after_seconds
        )
        reportable: dict[uuid.UUID, RefundAttempt] = {}
        for attempt in self.repository.list_reconcilable_refunds(
            unresolved_before=cutoff
        ):
            if attempt.status in {
                RefundStatus.PENDING.value,
                RefundStatus.UNKNOWN.value,
            }:
                result = self.gateway.lookup_refund(
                    idempotency_key=attempt.idempotency_key
                )
                if result is None:
                    if attempt.status == RefundStatus.PENDING.value:
                        self._set_refund_unknown(
                            attempt.id,
                            error="provider lookup could not determine refund outcome",
                        )
                    continue
                attempt = self._apply_refund_result(attempt.id, result)
            if (
                attempt.status == RefundStatus.SUCCEEDED.value
                and attempt.outcome_reported_at is None
            ):
                reportable[attempt.id] = attempt
        return list(reportable.values())

    def mark_refund_reported(self, attempt_id: uuid.UUID) -> None:
        attempt = self.repository.get_refund_by_id_for_update(attempt_id)
        if (
            attempt is None
            or attempt.status != RefundStatus.SUCCEEDED.value
            or attempt.outcome_reported_at is not None
        ):
            self.db.rollback()
            return
        attempt.outcome_reported_at = datetime.now(UTC)
        self.db.commit()

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
