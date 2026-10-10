import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.metrics import RESERVATION_REQUESTS, RESERVATIONS_SETTLED
from app.models import Product, ReservationStatus, StockReservation
from app.repositories.inventory_repository import (
    ProductRepository,
    ReservationRepository,
)
from app.schemas.inventory import ProductStock, ReservationActivity, ReserveItem


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


class ReservationConflictError(Exception):
    """An order ID was replayed with a different set of products or quantities."""

    def __init__(self, order_id: uuid.UUID):
        self.order_id = order_id
        super().__init__(f"order {order_id} already has a different reservation")


class InventoryService:
    def __init__(self, db: Session):
        self.db = db
        self.products = ProductRepository(db)
        self.reservations = ReservationRepository(db)

    def list_product_stock(self) -> list[ProductStock]:
        quantities = self.reservations.quantities_by_product()
        return [
            ProductStock(
                id=product.id,
                name=product.name,
                price=product.price,
                stock_qty=product.stock_qty,
                reserved_qty=quantities.get((product.id, ReservationStatus.HELD.value), 0),
                committed_qty=quantities.get(
                    (product.id, ReservationStatus.COMMITTED.value), 0
                ),
            )
            for product in self.products.list_all()
        ]

    def list_reservations(
        self,
        *,
        limit: int = 50,
        order_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> list[ReservationActivity]:
        return [
            ReservationActivity(
                id=reservation.id,
                order_id=reservation.order_id,
                product_id=reservation.product_id,
                product_name=product_name,
                qty=reservation.qty,
                status=reservation.status,
                expires_at=reservation.expires_at,
                created_at=reservation.created_at,
            )
            for reservation, product_name in self.reservations.list_recent(
                limit=limit, order_id=order_id, status=status
            )
        ]

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
        # The first lookup and all subsequent writes must form one serialized
        # operation. Product locks alone do not protect two deliveries carrying
        # the same order ID (especially when their product sets differ).
        self.reservations.lock_order(order_id)
        existing = self.reservations.list_for_order(order_id)
        if existing:
            # Idempotent: a replayed order_id returns its rows whatever their
            # status. Checking only held rows would re-deduct stock for an
            # order that was already committed or released.
            requested: dict[uuid.UUID, int] = {}
            recorded: dict[uuid.UUID, int] = {}
            for item in items:
                requested[item.product_id] = (
                    requested.get(item.product_id, 0) + item.qty
                )
            for reservation in existing:
                recorded[reservation.product_id] = (
                    recorded.get(reservation.product_id, 0) + reservation.qty
                )
            if requested != recorded:
                self.db.rollback()
                RESERVATION_REQUESTS.labels("conflict").inc()
                raise ReservationConflictError(order_id)
            RESERVATION_REQUESTS.labels("replayed").inc()
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
                RESERVATION_REQUESTS.labels("product_not_found").inc()
                raise ProductNotFoundError(item.product_id)
            if product.stock_qty < item.qty:
                self.db.rollback()
                RESERVATION_REQUESTS.labels("insufficient_stock").inc()
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
        RESERVATION_REQUESTS.labels("reserved").inc()
        for reservation in created:
            self.db.refresh(reservation)
        return created

    def commit_for_order(self, order_id: uuid.UUID) -> int:
        """Make held stock permanent once the order is paid.

        Stock was already deducted at reservation time, so committing only
        flips the status — but that is what stops a later release from
        handing paid-for units back to the shelf.
        """
        held = self.reservations.list_held_for_order(order_id, for_update=True)
        for reservation in held:
            reservation.status = ReservationStatus.COMMITTED.value
        self.db.commit()
        RESERVATIONS_SETTLED.labels("committed").inc(len(held))
        return len(held)

    def release_for_order(self, order_id: uuid.UUID) -> int:
        """Return held stock for an order (payment failure / cancel)."""
        # Row locks serialise this against commit_for_order for the same order:
        # whichever runs second sees no held rows and does nothing.
        held = self.reservations.list_held_for_order(order_id, for_update=True)
        if not held:
            self.db.rollback()
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
        RESERVATIONS_SETTLED.labels("released").inc(len(held))
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
