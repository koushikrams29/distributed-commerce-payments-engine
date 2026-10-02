import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from commerce_common.auth import AccessTokenPayload, Role
from commerce_common.events import EventType

from app.clients.inventory import (
    InsufficientStockError,
    InventoryClient,
    InventoryUnavailableError,
    ProductNotFoundError,
)
from app.clients.payment import PaymentClient, PaymentUnavailableError
from app.core.config import settings
from app.core.cursors import decode_cursor, encode_cursor
from app.core.db import SessionLocal
from app.models import Order, OrderItem, OrderStatus, OutboxEvent
from app.repositories.order_repository import OrderRepository
from app.repositories.outbox_repository import OutboxRepository
from app.schemas.order import OrderCreate, OrderListResponse


class OrderService:
    def __init__(
        self,
        db: Session,
        inventory: InventoryClient | None = None,
        payment: PaymentClient | None = None,
    ):
        self.db = db
        self.repository = OrderRepository(db)
        self.outbox = OutboxRepository(db)
        self.inventory = inventory or InventoryClient()
        self.payment = payment or PaymentClient()

    def create_order(
        self,
        payload: OrderCreate,
        *,
        user_id: uuid.UUID,
        access_token: str,
    ) -> tuple[Order, bool]:
        """Create an order as pending, priced from Inventory.

        When the event bus is enabled, an outbox row is written in the same
        transaction so a relay can publish order.created after commit (FR-1).
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
            if settings.use_event_bus:
                self._enqueue_order_created(order)
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

    # Every event handler locks the order row first, so two handlers (or a
    # handler and the reconciler) can never both act on the same old status.

    def on_inventory_reserved(self, order_id: uuid.UUID) -> None:
        order = self.repository.get_by_id_for_update(order_id)
        if order is None:
            return
        if order.status == OrderStatus.CANCELLED.value:
            # The reconciler gave up on this order before Inventory answered;
            # hand the stock back or it stays held forever.
            if settings.use_event_bus:
                self._enqueue_order_cancelled(order)
            self.db.commit()
            return
        if order.status != OrderStatus.PENDING.value:
            self.db.rollback()
            return

        order.status = OrderStatus.RESERVED.value
        if settings.use_event_bus:
            self._enqueue_charge_requested(order)
        self.db.commit()

    def on_inventory_failed(self, order_id: uuid.UUID) -> None:
        order = self.repository.get_by_id_for_update(order_id)
        if order is None or order.status != OrderStatus.PENDING.value:
            self.db.rollback()
            return
        order.status = OrderStatus.CANCELLED.value
        self.db.commit()

    def on_payment_succeeded(self, order_id: uuid.UUID) -> None:
        order = self.repository.get_by_id_for_update(order_id)
        if order is None:
            return
        if order.status == OrderStatus.CANCELLED.value:
            # The charge landed after the order was cancelled (and its stock
            # released): the customer paid for nothing, so refund them.
            if settings.use_event_bus:
                self._enqueue_refund_requested(order)
            self.db.commit()
            return
        if order.status != OrderStatus.RESERVED.value:
            self.db.rollback()
            return

        order.status = OrderStatus.PAID.value
        if settings.use_event_bus:
            self._enqueue_order_paid(order)
        self.db.commit()

    def on_payment_failed(self, order_id: uuid.UUID) -> None:
        order = self.repository.get_by_id_for_update(order_id)
        if order is None or order.status != OrderStatus.RESERVED.value:
            self.db.rollback()
            return
        order.status = OrderStatus.CANCELLED.value
        if settings.use_event_bus:
            self._enqueue_order_cancelled(order)
        self.db.commit()

    def on_inventory_committed(self, order_id: uuid.UUID) -> None:
        order = self.repository.get_by_id_for_update(order_id)
        if order is None or order.status != OrderStatus.PAID.value:
            self.db.rollback()
            return
        order.status = OrderStatus.FULFILLED.value
        if settings.use_event_bus:
            self._enqueue_order_fulfilled(order)
        self.db.commit()

    def reconcile_stuck_orders(self) -> int:
        """Drive orders stuck mid-saga towards a terminal status (FR-5).

        `pending` and `reserved` orders past their timeout are cancelled.
        `paid` orders are never cancelled — the money has been taken — so
        the stalled `order.paid` step is re-sent instead. Returns the number
        of orders acted on.
        """
        now = datetime.now(UTC)
        pending_before = now - timedelta(
            minutes=settings.reconcile_pending_after_minutes
        )
        reserved_before = now - timedelta(
            minutes=settings.reconcile_reserved_after_minutes
        )
        paid_before = now - timedelta(minutes=settings.reconcile_paid_after_minutes)
        acted_on = 0

        for order in self.repository.list_stuck_orders(
            status=OrderStatus.PENDING.value, created_before=pending_before
        ):
            order.status = OrderStatus.CANCELLED.value
            if settings.use_event_bus:
                # Inventory may still reserve for this order; releasing is a
                # no-op if it never did.
                self._enqueue_order_cancelled(order)
            acted_on += 1

        for order in self.repository.list_stuck_orders(
            status=OrderStatus.RESERVED.value, created_before=reserved_before
        ):
            order.status = OrderStatus.CANCELLED.value
            if settings.use_event_bus:
                self._enqueue_order_cancelled(order)
            acted_on += 1

        if settings.use_event_bus:
            for order in self.repository.list_stuck_orders(
                status=OrderStatus.PAID.value, updated_before=paid_before
            ):
                self._enqueue_order_paid(order)
                # Restart the clock so the next retry waits a full interval.
                order.updated_at = now
                acted_on += 1

        self.db.commit()
        return acted_on

    def reserve_inventory(self, order_id: uuid.UUID, *, access_token: str) -> None:
        """HTTP fallback when USE_EVENT_BUS=false (tests / local without RabbitMQ)."""
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
                return

            order.status = OrderStatus.RESERVED.value
            db.commit()
            self.charge_payment(order_id, access_token=access_token)
        finally:
            db.close()

    def charge_payment(self, order_id: uuid.UUID, *, access_token: str) -> None:
        """HTTP fallback when USE_EVENT_BUS=false."""
        db = SessionLocal()
        try:
            repository = OrderRepository(db)
            order = repository.get_by_id(order_id)
            if order is None or order.status != OrderStatus.RESERVED.value:
                return

            try:
                result = self.payment.charge(
                    order_id=order.id,
                    amount=order.total_amount,
                    idempotency_key=order.idempotency_key,
                    access_token=access_token,
                )
            except PaymentUnavailableError:
                return

            if result.status == "succeeded":
                order.status = OrderStatus.PAID.value
                db.commit()
                try:
                    self.inventory.commit(order_id=order.id, access_token=access_token)
                except InventoryUnavailableError:
                    return
                order.status = OrderStatus.FULFILLED.value
                db.commit()
                return

            order.status = OrderStatus.CANCELLED.value
            db.commit()
            try:
                self.inventory.release(
                    order_id=order.id, access_token=access_token
                )
            except InventoryUnavailableError:
                return
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

    def _enqueue_order_created(self, order: Order) -> None:
        self.outbox.add(
            OutboxEvent(
                aggregate_id=order.id,
                event_type=EventType.ORDER_CREATED,
                payload_json={
                    "order_id": str(order.id),
                    "items": [
                        {"product_id": str(item.product_id), "qty": item.qty}
                        for item in order.items
                    ],
                },
            )
        )

    def _enqueue_charge_requested(self, order: Order) -> None:
        self.outbox.add(
            OutboxEvent(
                aggregate_id=order.id,
                event_type=EventType.CHARGE_REQUESTED,
                payload_json={
                    "order_id": str(order.id),
                    "amount": str(order.total_amount),
                    "idempotency_key": order.idempotency_key,
                    "items": [
                        {"product_id": str(item.product_id), "qty": item.qty}
                        for item in order.items
                    ],
                },
            )
        )

    def _enqueue_order_cancelled(self, order: Order) -> None:
        self._enqueue(order, EventType.ORDER_CANCELLED)

    def _enqueue_order_paid(self, order: Order) -> None:
        self._enqueue(order, EventType.ORDER_PAID)

    def _enqueue_refund_requested(self, order: Order) -> None:
        self._enqueue(order, EventType.REFUND_REQUESTED)

    def _enqueue_order_fulfilled(self, order: Order) -> None:
        self._enqueue(
            order,
            EventType.ORDER_FULFILLED,
            user_id=str(order.user_id),
            total_amount=str(order.total_amount),
        )

    def _enqueue(self, order: Order, event_type: str, **extra: str) -> None:
        self.outbox.add(
            OutboxEvent(
                aggregate_id=order.id,
                event_type=event_type,
                payload_json={"order_id": str(order.id), **extra},
            )
        )

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
