import logging
import uuid
from decimal import Decimal
from typing import Any

from commerce_common.events import EventType
from commerce_common.messaging import publish_event, run_consumer

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import Payment, PaymentStatus
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
                context=(
                    {"items": payload["items"]} if payload.get("items") else None
                ),
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
        if payment.status in {
            PaymentStatus.SUCCEEDED.value,
            PaymentStatus.FAILED.value,
        }:
            _publish_payment_outcome(PaymentService(db), payment)
        else:
            logger.warning(
                "payment outcome unresolved; awaiting reconciliation payment_id=%s status=%s",
                payment.id,
                payment.status,
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


def _publish_payment_outcome(service: PaymentService, payment: Payment) -> None:
    event_payload: dict[str, Any] = {
        "order_id": str(payment.order_id),
        "payment_id": str(payment.id),
        "amount": str(payment.amount),
    }
    if payment.context_json and payment.context_json.get("items"):
        event_payload["items"] = payment.context_json["items"]
    routing_key = (
        EventType.PAYMENT_SUCCEEDED
        if payment.status == PaymentStatus.SUCCEEDED.value
        else EventType.PAYMENT_FAILED
    )
    publish_event(settings.rabbitmq_url, routing_key, event_payload)
    service.mark_outcome_reported(payment.id)


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
