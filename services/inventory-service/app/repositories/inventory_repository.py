import uuid
from datetime import datetime

from sqlalchemy import select
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

    def list_held_for_order(self, order_id: uuid.UUID) -> list[StockReservation]:
        stmt = select(StockReservation).where(
            StockReservation.order_id == order_id,
            StockReservation.status == ReservationStatus.HELD.value,
        )
        return list(self.db.execute(stmt).scalars().all())

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
