import logging
import uuid
from typing import Any

from commerce_common.events import EventType
from commerce_common.messaging import run_consumer

from app.core.config import settings
from app.core.db import SessionLocal
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


def _handle_order_fulfilled(routing_key: str, payload: dict[str, Any]) -> None:
    # Bindings outlive code changes: a queue created before this consumer
    # moved off payment.succeeded still receives it, so filter explicitly.
    if routing_key != EventType.ORDER_FULFILLED:
        logger.info("ignored %s on notification queue", routing_key)
        return
    order_id = uuid.UUID(payload["order_id"])

    db = SessionLocal()
    try:
        NotificationService(db).send_order_confirmation(order_id=order_id)
    finally:
        db.close()


def start_notification_event_consumers() -> None:
    run_consumer(
        url=settings.rabbitmq_url,
        queue_name="notification.events",
        routing_keys=[EventType.ORDER_FULFILLED],
        handler=_handle_order_fulfilled,
    )
    logger.info("notification consumer listening for %s", EventType.ORDER_FULFILLED)
