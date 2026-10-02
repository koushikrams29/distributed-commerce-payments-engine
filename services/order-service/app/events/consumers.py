import logging
import uuid
from decimal import Decimal
from typing import Any

from commerce_common.events import EventType
from commerce_common.messaging import run_consumer

from app.core.config import settings
from app.core.db import SessionLocal
from app.services.order_service import OrderService

logger = logging.getLogger(__name__)


def start_order_event_consumers() -> None:
    run_consumer(
        url=settings.rabbitmq_url,
        queue_name="order.events",
        routing_keys=[
            EventType.INVENTORY_RESERVED,
            EventType.INVENTORY_FAILED,
            EventType.PAYMENT_SUCCEEDED,
            EventType.PAYMENT_FAILED,
            EventType.INVENTORY_COMMITTED,
        ],
        handler=_dispatch,
    )


def _dispatch(routing_key: str, payload: dict[str, Any]) -> None:
    order_id = uuid.UUID(payload["order_id"])
    db = SessionLocal()
    try:
        service = OrderService(db)
        if routing_key == EventType.INVENTORY_RESERVED:
            service.on_inventory_reserved(order_id)
        elif routing_key == EventType.INVENTORY_FAILED:
            service.on_inventory_failed(order_id)
        elif routing_key == EventType.PAYMENT_SUCCEEDED:
            service.on_payment_succeeded(order_id)
        elif routing_key == EventType.PAYMENT_FAILED:
            service.on_payment_failed(order_id)
        elif routing_key == EventType.INVENTORY_COMMITTED:
            service.on_inventory_committed(order_id)
        else:
            logger.warning("ignored unknown inbound event: %s", routing_key)
    finally:
        db.close()
