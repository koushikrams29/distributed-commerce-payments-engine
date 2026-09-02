import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CoPurchaseCount, RecordedOrder


def canonical_pair(
    product_id_a: uuid.UUID, product_id_b: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    if str(product_id_a) <= str(product_id_b):
        return product_id_a, product_id_b
    return product_id_b, product_id_a


class RecommendationRepository:
    def __init__(self, db: Session):
        self.db = db

    def is_order_recorded(self, order_id: uuid.UUID) -> bool:
        return self.db.get(RecordedOrder, order_id) is not None

    def mark_order_recorded(self, order_id: uuid.UUID) -> None:
        self.db.add(RecordedOrder(order_id=order_id))
        self.db.flush()

    def increment_pair(self, product_id_a: uuid.UUID, product_id_b: uuid.UUID) -> None:
        a, b = canonical_pair(product_id_a, product_id_b)
        stmt = select(CoPurchaseCount).where(
            CoPurchaseCount.product_id_a == a,
            CoPurchaseCount.product_id_b == b,
        )
        row = self.db.execute(stmt).scalar_one_or_none()
        if row is None:
            row = CoPurchaseCount(product_id_a=a, product_id_b=b, count=1)
            self.db.add(row)
        else:
            row.count += 1
        self.db.flush()

    def top_recommendations_for(
        self, product_id: uuid.UUID, *, limit: int
    ) -> list[tuple[uuid.UUID, int]]:
        stmt_a = (
            select(CoPurchaseCount.product_id_b, CoPurchaseCount.count)
            .where(CoPurchaseCount.product_id_a == product_id)
            .order_by(CoPurchaseCount.count.desc())
            .limit(limit)
        )
        stmt_b = (
            select(CoPurchaseCount.product_id_a, CoPurchaseCount.count)
            .where(CoPurchaseCount.product_id_b == product_id)
            .order_by(CoPurchaseCount.count.desc())
            .limit(limit)
        )
        rows = list(self.db.execute(stmt_a).all()) + list(self.db.execute(stmt_b).all())
        merged: dict[uuid.UUID, int] = {}
        for other_id, count in rows:
            merged[other_id] = merged.get(other_id, 0) + count
        ranked = sorted(merged.items(), key=lambda item: item[1], reverse=True)
        return ranked[:limit]
