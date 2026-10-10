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


class MockPaymentGateway:
    """Deterministic stand-in for Stripe/Razorpay until a real gateway is wired."""

    def __init__(
        self,
        outcome: str | None = None,
        *,
        timeout_resolution: str | None = None,
        latency_seconds: float | None = None,
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

    def refund(self, amount: Decimal) -> None:
        del amount
