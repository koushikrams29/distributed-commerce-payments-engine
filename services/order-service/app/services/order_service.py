import uuid
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Order, OrderItem, OrderStatus
from app.repositories.order_repository import OrderRepository
from app.schemas.order import OrderCreate

# Placeholder until the Inventory Service owns the product catalogue.
PLACEHOLDER_UNIT_PRICE = Decimal("100.00")


class OrderService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = OrderRepository(db)

    def create_order(
        self, payload: OrderCreate, *, user_id: uuid.UUID
    ) -> tuple[Order, bool]:
        """Create an order, or return the existing one for a replayed request.

        Returns (order, created) where created is False when this request was
        a replay of one already processed for this user.
        """
        existing = self.repository.get_by_idempotency_key(
            user_id=user_id, idempotency_key=payload.idempotency_key
        )
        if existing is not None:
            return existing, False

        order = self._build_order(payload, user_id=user_id)

        try:
            self.repository.add(order)
            self.db.commit()
        except IntegrityError:
            # A concurrent request with the same (user, key) committed first.
            self.db.rollback()
            existing = self.repository.get_by_idempotency_key(
                user_id=user_id, idempotency_key=payload.idempotency_key
            )
            if existing is None:
                raise
            return existing, False

        self.db.refresh(order)
        return order, True

    def get_order(self, order_id: uuid.UUID) -> Order | None:
        return self.repository.get_by_id(order_id)

    def _build_order(self, payload: OrderCreate, *, user_id: uuid.UUID) -> Order:
        items = [
            OrderItem(
                product_id=item.product_id,
                qty=item.qty,
                unit_price=self._resolve_unit_price(item.product_id),
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

    def _resolve_unit_price(self, product_id: uuid.UUID) -> Decimal:
        return PLACEHOLDER_UNIT_PRICE
