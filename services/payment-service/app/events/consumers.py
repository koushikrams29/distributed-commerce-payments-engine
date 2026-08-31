import logging
import uuid
from decimal import Decimal
from typing import Any

from commerce_common.events import EventType
from commerce_common.messaging import publish_event, run_consumer

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import PaymentStatus
from app.services.payment_service import PaymentService

logger = logging.getLogger(__name__)


def _handle_charge_requested(_routing_key: str, payload: dict[str, Any]) -> None:
    order_id = uuid.UUID(payload["order_id"])
    amount = Decimal(str(payload["amount"]))
    idempotency_key = payload["idempotency_key"]

    db = SessionLocal()
    try:
        payment, _ = PaymentService(db).charge(
            order_id=order_id,
            amount=amount,
            idempotency_key=idempotency_key,
        )
        if payment.status == PaymentStatus.SUCCEEDED.value:
            publish_event(
                settings.rabbitmq_url,
                EventType.PAYMENT_SUCCEEDED,
                {
                    "order_id": str(order_id),
                    "payment_id": str(payment.id),
                    "amount": str(payment.amount),
                },
            )
        else:
            publish_event(
                settings.rabbitmq_url,
                EventType.PAYMENT_FAILED,
                {
                    "order_id": str(order_id),
                    "payment_id": str(payment.id),
                    "amount": str(payment.amount),
                },
            )
    finally:
        db.close()


def start_payment_event_consumers() -> None:
    run_consumer(
        url=settings.rabbitmq_url,
        queue_name="payment.events",
        routing_keys=[EventType.CHARGE_REQUESTED],
        handler=_handle_charge_requested,
    )
