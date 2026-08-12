"""HTTP client for the Inventory Service.

Until RabbitMQ exists, Order Service talks to Inventory over HTTP for catalogue
prices and stock reservation. The JWT is forwarded so Inventory can authorize
the call the same way a future gateway-proxied request would.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

import httpx

from app.core.config import settings


class InventoryError(Exception):
    """Base error for inventory integration failures."""


class ProductNotFoundError(InventoryError):
    def __init__(self, product_id: uuid.UUID):
        self.product_id = product_id
        super().__init__(f"product not found: {product_id}")


class InsufficientStockError(InventoryError):
    def __init__(self, detail: object):
        self.detail = detail
        super().__init__("insufficient stock")


class InventoryUnavailableError(InventoryError):
    """Inventory Service did not respond successfully."""


@dataclass(frozen=True)
class ProductInfo:
    id: uuid.UUID
    name: str
    price: Decimal
    stock_qty: int


class InventoryClient:
    def __init__(self, base_url: str | None = None, timeout: float = 5.0):
        self.base_url = (base_url or settings.inventory_service_url).rstrip("/")
        self.timeout = timeout

    def get_product(self, product_id: uuid.UUID, *, access_token: str) -> ProductInfo:
        try:
            response = httpx.get(
                f"{self.base_url}/products/{product_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise InventoryUnavailableError("inventory unreachable") from exc

        if response.status_code == 404:
            raise ProductNotFoundError(product_id)
        if response.status_code >= 400:
            raise InventoryUnavailableError(
                f"inventory returned {response.status_code}"
            )

        body = response.json()
        return ProductInfo(
            id=uuid.UUID(body["id"]),
            name=body["name"],
            price=Decimal(str(body["price"])),
            stock_qty=int(body["stock_qty"]),
        )

    def reserve(
        self,
        *,
        order_id: uuid.UUID,
        items: list[dict],
        access_token: str,
    ) -> None:
        try:
            response = httpx.post(
                f"{self.base_url}/reservations",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"order_id": str(order_id), "items": items},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise InventoryUnavailableError("inventory unreachable") from exc

        if response.status_code == 409:
            raise InsufficientStockError(response.json().get("detail"))
        if response.status_code == 404:
            raise ProductNotFoundError(uuid.UUID(int=0))  # fallback; detail has id
        if response.status_code >= 400:
            raise InventoryUnavailableError(
                f"inventory returned {response.status_code}"
            )
