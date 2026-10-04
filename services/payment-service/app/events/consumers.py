import logging
import uuid
from decimal import Decimal
from typing import Any

from commerce_common.events import EventType
from commerce_common.messaging import publish_event, run_consumer

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import PaymentStatus
from app.services.payment_service import IdempotencyKeyReusedError, PaymentService

logger = logging.getLogger(__name__)


def _handle_charge_requested(_routing_key: str, payload: dict[str, Any]) -> None:
    order_id = uuid.UUID(payload["order_id"])
    amount = Decimal(str(payload["amount"]))
    idempotency_key = payload["idempotency_key"]

    db = SessionLocal()
    try:
        try:
            payment, _ = PaymentService(db).charge(
                order_id=order_id,
                amount=amount,
                idempotency_key=idempotency_key,
            )
        except IdempotencyKeyReusedError as exc:
            logger.warning("refused charge for order %s: %s", order_id, exc)
            # Fail the order now instead of leaving it for the reconciler's timeout.
            publish_event(
                settings.rabbitmq_url,
                EventType.PAYMENT_FAILED,
                {"order_id": str(order_id), "amount": str(amount), "reason": str(exc)},
            )
            return
        if payment.status == PaymentStatus.SUCCEEDED.value:
            event_payload = {
                "order_id": str(order_id),
                "payment_id": str(payment.id),
                "amount": str(payment.amount),
            }
            if payload.get("items"):
                event_payload["items"] = payload["items"]
            publish_event(
                settings.rabbitmq_url,
                EventType.PAYMENT_SUCCEEDED,
                event_payload,
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


def _handle_refund_requested(_routing_key: str, payload: dict[str, Any]) -> None:
    order_id = uuid.UUID(payload["order_id"])
    db = SessionLocal()
    try:
        refunded = PaymentService(db).refund_for_order(order_id)
        for payment in refunded:
            publish_event(
                settings.rabbitmq_url,
                EventType.PAYMENT_REFUNDED,
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
        routing_keys=[EventType.CHARGE_REQUESTED, EventType.REFUND_REQUESTED],
        handler=_dispatch,
    )


def _dispatch(routing_key: str, payload: dict[str, Any]) -> None:
    if routing_key == EventType.CHARGE_REQUESTED:
        _handle_charge_requested(routing_key, payload)
    elif routing_key == EventType.REFUND_REQUESTED:
        _handle_refund_requested(routing_key, payload)
    else:
        logger.warning("ignored unknown inbound event: %s", routing_key)
