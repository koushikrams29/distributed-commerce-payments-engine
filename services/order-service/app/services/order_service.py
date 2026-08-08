import uuid
from decimal import Decimal

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

    def create_order(self, payload: OrderCreate) -> Order:
        items = [
            OrderItem(
                product_id=item.product_id,
                qty=item.qty,
                unit_price=self._resolve_unit_price(item.product_id),
            )
            for item in payload.items
        ]

        total_amount = sum(item.unit_price * item.qty for item in items)

        order = Order(
            user_id=payload.user_id,
            status=OrderStatus.PENDING.value,
            total_amount=total_amount,
            items=items,
        )

        self.repository.add(order)
        self.db.commit()
        self.db.refresh(order)
        return order

    def get_order(self, order_id: uuid.UUID) -> Order | None:
        return self.repository.get_by_id(order_id)

    def _resolve_unit_price(self, product_id: uuid.UUID) -> Decimal:
        return PLACEHOLDER_UNIT_PRICE