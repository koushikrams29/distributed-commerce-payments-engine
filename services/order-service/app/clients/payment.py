"""HTTP client for the Payment Service.

Used only when the event bus is off (USE_EVENT_BUS=false); otherwise charges
travel as events. The caller's JWT is forwarded so Payment authorizes the call itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

import httpx

from app.core.config import settings


class PaymentError(Exception):
    """Base error for payment integration failures."""


class PaymentUnavailableError(PaymentError):
    """Payment Service did not respond successfully."""


@dataclass(frozen=True)
class ChargeResult:
    payment_id: uuid.UUID
    order_id: uuid.UUID
    status: str
    amount: Decimal


class PaymentClient:
    def __init__(self, base_url: str | None = None, timeout: float = 5.0):
        self.base_url = (base_url or settings.payment_service_url).rstrip("/")
        self.timeout = timeout

    def charge(
        self,
        *,
        order_id: uuid.UUID,
        amount: Decimal,
        idempotency_key: str,
        access_token: str,
    ) -> ChargeResult:
        try:
            response = httpx.post(
                f"{self.base_url}/charges",
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "order_id": str(order_id),
                    "amount": str(amount),
                    "idempotency_key": idempotency_key,
                },
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise PaymentUnavailableError("payment unreachable") from exc

        if response.status_code not in (200, 201):
            raise PaymentUnavailableError(
                f"payment returned {response.status_code}"
            )

        body = response.json()
        return ChargeResult(
            payment_id=uuid.UUID(body["payment_id"]),
            order_id=uuid.UUID(body["order_id"]),
            status=body["status"],
            amount=Decimal(str(body["amount"])),
        )
