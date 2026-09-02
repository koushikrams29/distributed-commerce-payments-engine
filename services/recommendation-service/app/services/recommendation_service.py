import logging
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories.recommendation_repository import RecommendationRepository

logger = logging.getLogger(__name__)


class RecommendationService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = RecommendationRepository(db)

    def record_purchase(self, *, order_id: uuid.UUID, items: list[dict[str, Any]]) -> bool:
        """Increment co-purchase counts for all product pairs in an order (FR-9).

        Returns True when stats were updated, False when this order was already recorded.
        """
        if self.repository.is_order_recorded(order_id):
            return False

        product_ids = sorted(
            {uuid.UUID(item["product_id"]) for item in items},
            key=str,
        )
        if len(product_ids) < 2:
            self.repository.mark_order_recorded(order_id)
            self.db.commit()
            return True

        try:
            self.repository.mark_order_recorded(order_id)
            for i, product_a in enumerate(product_ids):
                for product_b in product_ids[i + 1 :]:
                    self.repository.increment_pair(product_a, product_b)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            return False

        logger.info(
            "recorded co-purchase stats for order=%s products=%s",
            order_id,
            [str(pid) for pid in product_ids],
        )
        return True

    def get_recommendations(
        self, product_id: uuid.UUID, *, limit: int | None = None
    ) -> list[dict[str, object]]:
        limit = limit or settings.recommendation_limit
        rows = self.repository.top_recommendations_for(product_id, limit=limit)
        return [
            {"product_id": str(other_id), "co_purchase_count": count}
            for other_id, count in rows
        ]
