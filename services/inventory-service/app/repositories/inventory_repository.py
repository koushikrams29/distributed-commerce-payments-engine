import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Product, ReservationStatus, StockReservation


class ProductRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, product: Product) -> Product:
        self.db.add(product)
        self.db.flush()
        return product

    def get_by_id(self, product_id: uuid.UUID) -> Product | None:
        stmt = select(Product).where(Product.id == product_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_id_for_update(self, product_id: uuid.UUID) -> Product | None:
        """Lock the product row until this transaction commits or rolls back."""
        stmt = (
            select(Product).where(Product.id == product_id).with_for_update()
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_all(self) -> list[Product]:
        stmt = select(Product).order_by(Product.name.asc())
        return list(self.db.execute(stmt).scalars().all())

    def get_by_name(self, name: str) -> Product | None:
        stmt = select(Product).where(Product.name == name)
        return self.db.execute(stmt).scalar_one_or_none()


class ReservationRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, reservation: StockReservation) -> StockReservation:
        self.db.add(reservation)
        self.db.flush()
        return reservation

    def list_held_for_order(
        self, order_id: uuid.UUID, *, for_update: bool = False
    ) -> list[StockReservation]:
        stmt = select(StockReservation).where(
            StockReservation.order_id == order_id,
            StockReservation.status == ReservationStatus.HELD.value,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return list(self.db.execute(stmt).scalars().all())

    def list_for_order(self, order_id: uuid.UUID) -> list[StockReservation]:
        stmt = select(StockReservation).where(StockReservation.order_id == order_id)
        return list(self.db.execute(stmt).scalars().all())

    def quantities_by_product(self) -> dict[tuple[uuid.UUID, str], int]:
        """Units per (product, reservation status)."""
        stmt = select(
            StockReservation.product_id,
            StockReservation.status,
            func.sum(StockReservation.qty),
        ).group_by(StockReservation.product_id, StockReservation.status)
        return {
            (product_id, status): int(total)
            for product_id, status, total in self.db.execute(stmt).all()
        }

    def list_recent(
        self,
        *,
        limit: int,
        order_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> list[tuple[StockReservation, str]]:
        """Newest first, each with its product's name."""
        stmt = (
            select(StockReservation, Product.name)
            .join(Product, Product.id == StockReservation.product_id)
            .order_by(StockReservation.created_at.desc(), StockReservation.id.desc())
            .limit(limit)
        )
        if order_id is not None:
            stmt = stmt.where(StockReservation.order_id == order_id)
        if status is not None:
            stmt = stmt.where(StockReservation.status == status)
        return [(reservation, name) for reservation, name in self.db.execute(stmt).all()]

    def list_held_for_product(self, product_id: uuid.UUID) -> list[StockReservation]:
        stmt = (
            select(StockReservation)
            .where(
                StockReservation.product_id == product_id,
                StockReservation.status == ReservationStatus.HELD.value,
            )
            .order_by(StockReservation.created_at.desc())
        )
        return list(self.db.execute(stmt).scalars().all())
