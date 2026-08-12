import uuid
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from commerce_common.auth import AccessTokenPayload, Role

from app.clients.inventory import (
    InsufficientStockError,
    InventoryClient,
    InventoryUnavailableError,
    ProductNotFoundError,
)
from app.core.cursors import decode_cursor, encode_cursor
from app.core.db import SessionLocal
from app.models import Order, OrderItem, OrderStatus
from app.repositories.order_repository import OrderRepository
from app.schemas.order import OrderCreate, OrderListResponse


class OrderService:
    def __init__(
        self, db: Session, inventory: InventoryClient | None = None
    ):
        self.db = db
        self.repository = OrderRepository(db)
        self.inventory = inventory or InventoryClient()

    def create_order(
        self,
        payload: OrderCreate,
        *,
        user_id: uuid.UUID,
        access_token: str,
    ) -> tuple[Order, bool]:
        """Create an order as pending, priced from Inventory.

        Reservation runs after the response (BackgroundTasks) so FR-1 holds:
        the caller gets an order id without waiting on stock locking.
        """
        existing = self.repository.get_by_idempotency_key(
            user_id=user_id, idempotency_key=payload.idempotency_key
        )
        if existing is not None:
            return existing, False

        prices = self._fetch_prices(payload, access_token=access_token)
        order = self._build_order(payload, user_id=user_id, prices=prices)

        try:
            self.repository.add(order)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.repository.get_by_idempotency_key(
                user_id=user_id, idempotency_key=payload.idempotency_key
            )
            if existing is None:
                raise
            return existing, False

        self.db.refresh(order)
        return order, True

    def reserve_inventory(self, order_id: uuid.UUID, *, access_token: str) -> None:
        """Hold stock for a pending order; mark reserved or cancelled.

        Safe to call from a background task — opens its own DB session.
        """
        db = SessionLocal()
        try:
            repository = OrderRepository(db)
            order = repository.get_by_id(order_id)
            if order is None or order.status != OrderStatus.PENDING.value:
                return

            items = [
                {"product_id": str(item.product_id), "qty": item.qty}
                for item in order.items
            ]
            try:
                self.inventory.reserve(
                    order_id=order.id, items=items, access_token=access_token
                )
            except (InsufficientStockError, ProductNotFoundError):
                order.status = OrderStatus.CANCELLED.value
                db.commit()
                return
            except InventoryUnavailableError:
                # Leave pending — a reconciler / retry can pick it up later.
                return

            order.status = OrderStatus.RESERVED.value
            db.commit()
        finally:
            db.close()

    def get_order(self, order_id: uuid.UUID) -> Order | None:
        return self.repository.get_by_id(order_id)

    def get_order_for_viewer(
        self, order_id: uuid.UUID, *, viewer: AccessTokenPayload
    ) -> Order | None:
        order = self.repository.get_by_id(order_id)
        if order is None:
            return None
        if viewer.role != Role.ADMIN and order.user_id != viewer.user_id:
            return None
        return order

    def list_orders(
        self,
        *,
        limit: int = 20,
        status: str | None = None,
        cursor: str | None = None,
    ) -> OrderListResponse:
        after = decode_cursor(cursor) if cursor else None
        rows = self.repository.list_orders(limit=limit, status=status, after=after)

        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            next_cursor = encode_cursor(rows[-1])

        return OrderListResponse(items=rows, next_cursor=next_cursor)

    def _fetch_prices(
        self, payload: OrderCreate, *, access_token: str
    ) -> dict[uuid.UUID, Decimal]:
        prices: dict[uuid.UUID, Decimal] = {}
        for item in payload.items:
            if item.product_id in prices:
                continue
            product = self.inventory.get_product(
                item.product_id, access_token=access_token
            )
            prices[item.product_id] = product.price
        return prices

    def _build_order(
        self,
        payload: OrderCreate,
        *,
        user_id: uuid.UUID,
        prices: dict[uuid.UUID, Decimal],
    ) -> Order:
        items = [
            OrderItem(
                product_id=item.product_id,
                qty=item.qty,
                unit_price=prices[item.product_id],
            )
            for item in payload.items
        ]

        return Order(
            user_id=user_id,
            idempotency_key=payload.idempotency_key,
            status=OrderStatus.PENDING.value,
            total_amount=sum(item.unit_price * item.qty for item in items),
            items=items,
        )
