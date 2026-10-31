import time
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.core import config


class GatewayStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class GatewayResult:
    status: GatewayStatus
    reference: str


class GatewayTimeoutError(TimeoutError):
    """The request may have reached the provider; its outcome is unknown."""


class RefundLookupKind(str, Enum):
    """Outcomes of asking the provider about a prior refund attempt."""

    FOUND = "found"
    NOT_FOUND = "not_found"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RefundLookup:
    kind: RefundLookupKind
    result: GatewayResult | None = None

    @classmethod
    def found(cls, result: GatewayResult) -> "RefundLookup":
        return cls(kind=RefundLookupKind.FOUND, result=result)

    @classmethod
    def not_found(cls) -> "RefundLookup":
        return cls(kind=RefundLookupKind.NOT_FOUND)

    @classmethod
    def unknown(cls) -> "RefundLookup":
        return cls(kind=RefundLookupKind.UNKNOWN)


class MockPaymentGateway:
    """Deterministic stand-in for Stripe/Razorpay until a real gateway is wired.

    Refund lookups only invent an outcome for keys that were actually submitted
    via `refund()`. That makes the crash-before-call window testable: a durable
    pending attempt with no submission yields `not_found`, not a fake success.
    """

    def __init__(
        self,
        outcome: str | None = None,
        *,
        timeout_resolution: str | None = None,
        latency_seconds: float | None = None,
        refund_outcome: str | None = None,
        refund_timeout_resolution: str | None = None,
        refund_latency_seconds: float | None = None,
    ):
        self.outcome = outcome or config.settings.mock_payment_outcome
        self.timeout_resolution = (
            timeout_resolution or config.settings.mock_payment_timeout_resolution
        )
        self.latency_seconds = (
            config.settings.mock_payment_latency_seconds
            if latency_seconds is None
            else latency_seconds
        )
        self.refund_outcome = refund_outcome or config.settings.mock_refund_outcome
        self.refund_timeout_resolution = (
            refund_timeout_resolution
            or config.settings.mock_refund_timeout_resolution
        )
        self.refund_latency_seconds = (
            config.settings.mock_refund_latency_seconds
            if refund_latency_seconds is None
            else refund_latency_seconds
        )
        # idempotency_key -> GatewayResult, or None when submitted but timed out.
        self._submitted_refunds: dict[str, GatewayResult | None] = {}

    def charge(self, amount: Decimal, *, idempotency_key: str) -> GatewayResult:
        del amount
        if self.latency_seconds > 0:
            time.sleep(self.latency_seconds)
        if self.outcome == "timeout":
            raise GatewayTimeoutError("mock gateway timed out after submission")
        return self._result(self.outcome, idempotency_key=idempotency_key)

    def lookup(self, *, idempotency_key: str) -> GatewayResult | None:
        """Query an earlier ambiguous operation without submitting a new charge."""
        if self.outcome != "timeout":
            return self._result(self.outcome, idempotency_key=idempotency_key)
        if self.timeout_resolution == "unknown":
            return None
        return self._result(self.timeout_resolution, idempotency_key=idempotency_key)

    @staticmethod
    def _result(outcome: str, *, idempotency_key: str) -> GatewayResult:
        status = (
            GatewayStatus.SUCCEEDED
            if outcome == "success"
            else GatewayStatus.FAILED
        )
        return GatewayResult(status=status, reference=f"mock-{idempotency_key}")

    def refund(self, amount: Decimal, *, idempotency_key: str) -> GatewayResult:
        del amount
        if self.refund_latency_seconds > 0:
            time.sleep(self.refund_latency_seconds)
        if self.refund_outcome == "timeout":
            # Record that a request was submitted before the timeout so lookup
            # never confuses "never called" with "called, outcome unknown".
            self._submitted_refunds[idempotency_key] = None
            raise GatewayTimeoutError("mock refund timed out after submission")
        result = self._result(self.refund_outcome, idempotency_key=idempotency_key)
        self._submitted_refunds[idempotency_key] = result
        return result

    def lookup_refund(self, *, idempotency_key: str) -> RefundLookup:
        if idempotency_key not in self._submitted_refunds:
            return RefundLookup.not_found()
        stored = self._submitted_refunds[idempotency_key]
        if stored is not None:
            return RefundLookup.found(stored)
        if self.refund_timeout_resolution == "unknown":
            return RefundLookup.unknown()
        return RefundLookup.found(
            self._result(
                self.refund_timeout_resolution, idempotency_key=idempotency_key
            )
        )
