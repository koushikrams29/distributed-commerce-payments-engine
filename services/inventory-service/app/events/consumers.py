import logging
import uuid
from typing import Any

from commerce_common.events import EventType
from commerce_common.messaging import publish_event, run_consumer

from app.core.config import settings
from app.core.db import SessionLocal
from app.schemas.inventory import ReserveItem
from app.services.inventory_service import (
    InsufficientStockError,
    InventoryService,
    ProductNotFoundError,
)

logger = logging.getLogger(__name__)


def _handle_order_created(_routing_key: str, payload: dict[str, Any]) -> None:
    order_id = uuid.UUID(payload["order_id"])
    items = [
        ReserveItem(product_id=uuid.UUID(item["product_id"]), qty=item["qty"])
        for item in payload["items"]
    ]
    db = SessionLocal()
    try:
        service = InventoryService(db)
        try:
            reservations = service.reserve(order_id=order_id, items=items)
            publish_event(
                settings.rabbitmq_url,
                EventType.INVENTORY_RESERVED,
                {
                    "order_id": str(order_id),
                    "reservation_id": str(reservations[0].id),
                },
            )
        except (InsufficientStockError, ProductNotFoundError) as exc:
            publish_event(
                settings.rabbitmq_url,
                EventType.INVENTORY_FAILED,
                {"order_id": str(order_id), "reason": str(exc)},
            )
    finally:
        db.close()


def _handle_order_cancelled(_routing_key: str, payload: dict[str, Any]) -> None:
    order_id = uuid.UUID(payload["order_id"])
    db = SessionLocal()
    try:
        InventoryService(db).release_for_order(order_id)
    finally:
        db.close()


def start_inventory_event_consumers() -> None:
    run_consumer(
        url=settings.rabbitmq_url,
        queue_name="inventory.events",
        routing_keys=[EventType.ORDER_CREATED, EventType.ORDER_CANCELLED],
        handler=_dispatch,
    )


def _dispatch(routing_key: str, payload: dict[str, Any]) -> None:
    if routing_key == EventType.ORDER_CREATED:
        _handle_order_created(routing_key, payload)
    elif routing_key == EventType.ORDER_CANCELLED:
        _handle_order_cancelled(routing_key, payload)
    else:
        logger.warning("ignored unknown inbound event: %s", routing_key)
