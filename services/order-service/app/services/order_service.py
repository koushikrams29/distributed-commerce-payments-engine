import re
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
from app.core.metrics import RECONCILER_ACTIONS
from app.models import Order, OrderItem, OrderStatus, OutboxEvent
from app.repositories.order_repository import OrderRepository
from app.repositories.outbox_repository import OutboxRepository
from app.schemas.order import (
    OrderCreate,
    OrderEventRead,
    OrderListResponse,
    OrderSummary,
    OutboxBacklog,
    OverdueOrders,
)

_TRACEPARENT = re.compile(r"^[0-9a-f]{2}-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$")


def trace_id_from_context(trace_context: dict | None) -> str | None:
    """The trace ID inside a stored W3C `traceparent`, if there is a valid one."""
    traceparent = (trace_context or {}).get("traceparent")
    if not isinstance(traceparent, str):
        return None
    match = _TRACEPARENT.match(traceparent)
    if match is None or set(match.group(1)) == {"0"}:
        return None
    return match.group(1)


def _reconcile_cutoffs(now: datetime) -> tuple[datetime, datetime, datetime]:
    """(pending created before, reserved created before, paid updated before)."""
    return (
        now - timedelta(minutes=settings.reconcile_pending_after_minutes),
        now - timedelta(minutes=settings.reconcile_reserved_after_minutes),
        now - timedelta(minutes=settings.reconcile_paid_after_minutes),
    )


def payment_idempotency_key(order: Order) -> str:
    """The key Payment deduplicates charges on: one charge per order.

    The shopper's own key is only unique per shopper, but Payment's is global,
    so reusing it would let shopper B's order replay shopper A's charge.
    """
    return f"order-{order.id}"


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
                self._enqueue_status_changed(order, previous_status=None)
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

        self._set_status(order, OrderStatus.RESERVED)
        if settings.use_event_bus:
            self._enqueue_charge_requested(order)
        self.db.commit()

    def on_inventory_failed(self, order_id: uuid.UUID) -> None:
        order = self.repository.get_by_id_for_update(order_id)
        if order is None or order.status != OrderStatus.PENDING.value:
            self.db.rollback()
            return
        self._set_status(order, OrderStatus.CANCELLED)
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

        self._set_status(order, OrderStatus.PAID)
        if settings.use_event_bus:
            self._enqueue_order_paid(order)
        self.db.commit()

    def on_payment_failed(self, order_id: uuid.UUID) -> None:
        order = self.repository.get_by_id_for_update(order_id)
        if order is None or order.status != OrderStatus.RESERVED.value:
            self.db.rollback()
            return
        self._set_status(order, OrderStatus.CANCELLED)
        if settings.use_event_bus:
            self._enqueue_order_cancelled(order)
        self.db.commit()

    def on_inventory_committed(self, order_id: uuid.UUID) -> None:
        order = self.repository.get_by_id_for_update(order_id)
        if order is None or order.status != OrderStatus.PAID.value:
            self.db.rollback()
            return
        self._set_status(order, OrderStatus.FULFILLED)
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
        pending_before, reserved_before, paid_before = _reconcile_cutoffs(now)
        acted_on = 0

        for order in self.repository.list_stuck_orders(
            status=OrderStatus.PENDING.value, created_before=pending_before
        ):
            self._set_status(order, OrderStatus.CANCELLED)
            if settings.use_event_bus:
                # Inventory may still reserve for this order; releasing is a
                # no-op if it never did.
                self._enqueue_order_cancelled(order)
            acted_on += 1

        for order in self.repository.list_stuck_orders(
            status=OrderStatus.RESERVED.value, created_before=reserved_before
        ):
            self._set_status(order, OrderStatus.CANCELLED)
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
        RECONCILER_ACTIONS.inc(acted_on)
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
                    idempotency_key=payment_idempotency_key(order),
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

            if result.status == "failed":
                order.status = OrderStatus.CANCELLED.value
                db.commit()
                try:
                    self.inventory.release(
                        order_id=order.id, access_token=access_token
                    )
                except InventoryUnavailableError:
                    return
            # pending/unknown is deliberately not treated as a decline. The
            # outcome may still be a successful charge, so releasing stock now
            # would risk selling paid-for units to another customer.
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
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> OrderListResponse:
        after = decode_cursor(cursor) if cursor else None
        rows = self.repository.list_orders(
            limit=limit,
            status=status,
            after=after,
            created_from=created_from,
            created_to=created_to,
        )

        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            next_cursor = encode_cursor(rows[-1])

        return OrderListResponse(items=rows, next_cursor=next_cursor)

    def list_events(self, order_id: uuid.UUID) -> list[OrderEventRead] | None:
        """Every event emitted about the order, oldest first; None if no such order.

        Each status transition writes an order.status_changed row, so this is
        the order's saga history as this service recorded it.
        """
        if self.repository.get_by_id(order_id) is None:
            return None
        return [
            OrderEventRead(
                id=event.id,
                event_type=event.event_type,
                payload=event.payload_json,
                created_at=event.created_at,
                published_at=event.published_at,
                trace_id=trace_id_from_context(event.trace_context),
            )
            for event in self.outbox.list_for_aggregate(order_id)
        ]

    def summary(self) -> OrderSummary:
        now = datetime.now(UTC)
        counts = self.repository.count_by_status()
        pending_before, reserved_before, paid_before = _reconcile_cutoffs(now)
        unpublished, oldest_unpublished_at = self.outbox.backlog()
        overdue = [
            OverdueOrders(
                status=OrderStatus.PENDING.value,
                count=self.repository.count_overdue(
                    status=OrderStatus.PENDING.value, created_before=pending_before
                ),
                after_minutes=settings.reconcile_pending_after_minutes,
            ),
            OverdueOrders(
                status=OrderStatus.RESERVED.value,
                count=self.repository.count_overdue(
                    status=OrderStatus.RESERVED.value, created_before=reserved_before
                ),
                after_minutes=settings.reconcile_reserved_after_minutes,
            ),
            OverdueOrders(
                status=OrderStatus.PAID.value,
                count=self.repository.count_overdue(
                    status=OrderStatus.PAID.value, updated_before=paid_before
                ),
                after_minutes=settings.reconcile_paid_after_minutes,
            ),
        ]
        return OrderSummary(
            counts={status.value: counts.get(status.value, 0) for status in OrderStatus},
            total=sum(counts.values()),
            outbox=OutboxBacklog(
                unpublished=unpublished, oldest_unpublished_at=oldest_unpublished_at
            ),
            overdue=overdue,
            reconciler_enabled=settings.reconcile_enabled,
            reconcile_interval_seconds=settings.reconcile_poll_interval_seconds,
            generated_at=now,
        )

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
                    "idempotency_key": payment_idempotency_key(order),
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

    def _set_status(self, order: Order, status: OrderStatus) -> None:
        """The single place event-driven code changes status, so every
        transition reaches the live dashboard (FR-6)."""
        previous = order.status
        order.status = status.value
        if settings.use_event_bus:
            self._enqueue_status_changed(order, previous_status=previous)

    def _enqueue_status_changed(
        self, order: Order, *, previous_status: str | None
    ) -> None:
        self.outbox.add(
            OutboxEvent(
                aggregate_id=order.id,
                event_type=EventType.ORDER_STATUS_CHANGED,
                payload_json={
                    "order_id": str(order.id),
                    "user_id": str(order.user_id),
                    "status": order.status,
                    "previous_status": previous_status,
                    "total_amount": str(order.total_amount),
                    "occurred_at": datetime.now(UTC).isoformat(),
                },
            )
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
