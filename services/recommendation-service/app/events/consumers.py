import logging
import uuid
from typing import Any

from commerce_common.events import EventType
from commerce_common.messaging import run_consumer

from app.core.config import settings
from app.core.db import SessionLocal
from app.services.recommendation_service import RecommendationService

logger = logging.getLogger(__name__)


def _handle_payment_succeeded(routing_key: str, payload: dict[str, Any]) -> None:
    del routing_key
    order_id = uuid.UUID(payload["order_id"])
    items = payload.get("items") or []
    if not items:
        logger.warning("payment.succeeded for order=%s had no items; skipping", order_id)
        return

    db = SessionLocal()
    try:
        RecommendationService(db).record_purchase(order_id=order_id, items=items)
    finally:
        db.close()


def start_recommendation_event_consumers() -> None:
    run_consumer(
        url=settings.rabbitmq_url,
        queue_name="recommendation.events",
        routing_keys=[EventType.PAYMENT_SUCCEEDED],
        handler=_handle_payment_succeeded,
    )
    logger.info(
        "recommendation consumer listening for %s", EventType.PAYMENT_SUCCEEDED
    )
