import logging
import uuid
from typing import Any

from commerce_common.events import EventType
from commerce_common.messaging import run_consumer

from app.core.config import settings
from app.core.db import SessionLocal
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


def _handle_payment_succeeded(routing_key: str, payload: dict[str, Any]) -> None:
    del routing_key
    order_id = uuid.UUID(payload["order_id"])
    payment_id = uuid.UUID(payload["payment_id"]) if payload.get("payment_id") else None

    db = SessionLocal()
    try:
        NotificationService(db).send_order_confirmation(
            order_id=order_id, payment_id=payment_id
        )
    finally:
        db.close()


def start_notification_event_consumers() -> None:
    run_consumer(
        url=settings.rabbitmq_url,
        queue_name="notification.events",
        routing_keys=[EventType.PAYMENT_SUCCEEDED],
        handler=_handle_payment_succeeded,
    )
    logger.info("notification consumer listening for %s", EventType.PAYMENT_SUCCEEDED)
