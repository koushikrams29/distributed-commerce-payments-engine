from decimal import Decimal

from app.core import config


class MockPaymentGateway:
    """Deterministic stand-in for Stripe/Razorpay until a real gateway is wired."""

    def __init__(self, outcome: str | None = None):
        self.outcome = (outcome or config.settings.mock_payment_outcome).lower()

    def charge(self, amount: Decimal) -> bool:
        del amount
        return self.outcome == "success"
