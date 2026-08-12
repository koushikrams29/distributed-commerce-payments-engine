import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Product, ReservationStatus, StockReservation
from app.repositories.inventory_repository import (
    ProductRepository,
    ReservationRepository,
)
from app.schemas.inventory import ReserveItem


class InsufficientStockError(Exception):
    def __init__(self, product_id: uuid.UUID, requested: int, available: int):
        self.product_id = product_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"insufficient stock for {product_id}: requested {requested}, available {available}"
        )


class ProductNotFoundError(Exception):
    def __init__(self, product_id: uuid.UUID):
        self.product_id = product_id
        super().__init__(f"product not found: {product_id}")


class InventoryService:
    def __init__(self, db: Session):
        self.db = db
        self.products = ProductRepository(db)
        self.reservations = ReservationRepository(db)

    def list_products(self) -> list[Product]:
        return self.products.list_all()

    def get_product(self, product_id: uuid.UUID) -> Product | None:
        return self.products.get_by_id(product_id)

    def list_active_reservations(
        self, product_id: uuid.UUID
    ) -> list[StockReservation]:
        return self.reservations.list_held_for_product(product_id)

    def reserve(
        self, *, order_id: uuid.UUID, items: list[ReserveItem]
    ) -> list[StockReservation]:
        """Atomically hold stock for an order.

        Each product row is locked with SELECT ... FOR UPDATE so two concurrent
        reservations cannot both decide the same unit is available (FR-2).
        """
        existing = self.reservations.list_held_for_order(order_id)
        if existing:
            # Idempotent: replaying the same order_id returns the held rows.
            return existing

        # Lock products in a stable order to avoid deadlocks between requests
        # that reserve overlapping sets of products.
        sorted_items = sorted(items, key=lambda item: str(item.product_id))
        created: list[StockReservation] = []
        expires_at = datetime.now(UTC) + timedelta(
            minutes=settings.reservation_ttl_minutes
        )

        for item in sorted_items:
            product = self.products.get_by_id_for_update(item.product_id)
            if product is None:
                self.db.rollback()
                raise ProductNotFoundError(item.product_id)
            if product.stock_qty < item.qty:
                self.db.rollback()
                raise InsufficientStockError(
                    item.product_id, item.qty, product.stock_qty
                )

            product.stock_qty -= item.qty
            reservation = StockReservation(
                order_id=order_id,
                product_id=item.product_id,
                qty=item.qty,
                status=ReservationStatus.HELD.value,
                expires_at=expires_at,
            )
            self.reservations.add(reservation)
            created.append(reservation)

        self.db.commit()
        for reservation in created:
            self.db.refresh(reservation)
        return created

    def release_for_order(self, order_id: uuid.UUID) -> int:
        """Return held stock for an order (payment failure / cancel)."""
        held = self.reservations.list_held_for_order(order_id)
        if not held:
            return 0

        # Lock products before restoring qty.
        product_ids = sorted({str(r.product_id) for r in held})
        products_by_id: dict[uuid.UUID, Product] = {}
        for product_id_str in product_ids:
            product_id = uuid.UUID(product_id_str)
            product = self.products.get_by_id_for_update(product_id)
            if product is None:
                self.db.rollback()
                raise ProductNotFoundError(product_id)
            products_by_id[product_id] = product

        for reservation in held:
            products_by_id[reservation.product_id].stock_qty += reservation.qty
            reservation.status = ReservationStatus.RELEASED.value

        self.db.commit()
        return len(held)

    def ensure_product(
        self, *, name: str, price: Decimal, stock_qty: int
    ) -> Product:
        existing = self.products.get_by_name(name)
        if existing is not None:
            return existing
        product = Product(name=name, price=price, stock_qty=stock_qty)
        self.products.add(product)
        self.db.commit()
        self.db.refresh(product)
        return product
