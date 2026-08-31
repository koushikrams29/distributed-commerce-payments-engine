"""Minimal RabbitMQ helpers shared across services."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

import pika
from pika.adapters.blocking_connection import BlockingChannel

from commerce_common.events.types import EVENT_EXCHANGE

logger = logging.getLogger(__name__)

EventHandler = Callable[[str, dict[str, Any]], None]


def declare_exchange(channel: BlockingChannel) -> None:
    channel.exchange_declare(
        exchange=EVENT_EXCHANGE, exchange_type="topic", durable=True
    )


def publish_event(url: str, routing_key: str, payload: dict[str, Any]) -> None:
    connection = pika.BlockingConnection(pika.URLParameters(url))
    try:
        channel = connection.channel()
        declare_exchange(channel)
        channel.basic_publish(
            exchange=EVENT_EXCHANGE,
            routing_key=routing_key,
            body=json.dumps(payload),
            properties=pika.BasicProperties(
                delivery_mode=2, content_type="application/json"
            ),
        )
    finally:
        connection.close()


def run_consumer(
    *,
    url: str,
    queue_name: str,
    routing_keys: list[str],
    handler: EventHandler,
) -> threading.Thread:
    """Start a daemon thread that blocks on basic_consume."""

    def _consume() -> None:
        connection = pika.BlockingConnection(pika.URLParameters(url))
        channel = connection.channel()
        declare_exchange(channel)
        channel.queue_declare(queue=queue_name, durable=True)
        for routing_key in routing_keys:
            channel.queue_bind(
                queue=queue_name, exchange=EVENT_EXCHANGE, routing_key=routing_key
            )
        channel.basic_qos(prefetch_count=1)

        def _callback(
            ch: BlockingChannel,
            method: pika.spec.Basic.Deliver,
            _properties: pika.spec.BasicProperties,
            body: bytes,
        ) -> None:
            try:
                payload = json.loads(body)
                handler(method.routing_key, payload)
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception:
                logger.exception("event handler failed for %s", routing_keys)
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

        channel.basic_consume(queue=queue_name, on_message_callback=_callback)
        logger.info("consumer started on queue=%s keys=%s", queue_name, routing_keys)
        channel.start_consuming()

    thread = threading.Thread(target=_consume, name=f"rmq-{queue_name}", daemon=True)
    thread.start()
    return thread
