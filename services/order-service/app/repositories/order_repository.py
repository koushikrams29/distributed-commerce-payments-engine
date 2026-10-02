import uuid
from datetime import datetime

from sqlalchemy import Select, select, tuple_
from sqlalchemy.orm import Session, selectinload

from app.models import Order


class OrderRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, order: Order) -> Order:
        self.db.add(order)
        self.db.flush()
        return order

    def get_by_id(self, order_id: uuid.UUID) -> Order | None:
        stmt = select(Order).where(Order.id == order_id).options(selectinload(Order.items))
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_id_for_update(self, order_id: uuid.UUID) -> Order | None:
        """Lock the order row so concurrent status transitions serialise."""
        stmt = (
            select(Order)
            .where(Order.id == order_id)
            .with_for_update()
            .options(selectinload(Order.items))
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_idempotency_key(
        self, *, user_id: uuid.UUID, idempotency_key: str
    ) -> Order | None:
        stmt = (
            select(Order)
            .where(
                Order.user_id == user_id,
                Order.idempotency_key == idempotency_key,
            )
            .options(selectinload(Order.items))
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_orders(
        self,
        *,
        limit: int,
        status: str | None = None,
        after: tuple[datetime, uuid.UUID] | None = None,
    ) -> list[Order]:
        """Newest first. Fetch limit+1 so the service can detect a next page."""
        stmt: Select[tuple[Order]] = (
            select(Order)
            .options(selectinload(Order.items))
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(limit + 1)
        )
        if status is not None:
            stmt = stmt.where(Order.status == status)
        if after is not None:
            created_at, order_id = after
            stmt = stmt.where(
                tuple_(Order.created_at, Order.id) < tuple_(created_at, order_id)
            )
        return list(self.db.execute(stmt).scalars().all())

    def list_stuck_orders(
        self,
        *,
        status: str,
        created_before: datetime | None = None,
        updated_before: datetime | None = None,
    ) -> list[Order]:
        """Lock stuck orders, skipping rows an event handler is mid-way through.

        A skipped row is either about to change status (so no longer stuck) or
        will be picked up on the next reconciler pass.
        """
        stmt = (
            select(Order)
            .where(Order.status == status)
            .with_for_update(skip_locked=True)
            .options(selectinload(Order.items))
        )
        if created_before is not None:
            stmt = stmt.where(Order.created_at < created_before)
        if updated_before is not None:
            stmt = stmt.where(Order.updated_at < updated_before)
        return list(self.db.execute(stmt).scalars().all())
