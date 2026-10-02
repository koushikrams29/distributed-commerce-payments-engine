"""Minimal RabbitMQ helpers shared across services."""

from __future__ import annotations

import json
import logging
import threading
import time
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
    queue_name: str | None,
    routing_keys: list[str],
    handler: EventHandler,
    reconnect_delay_seconds: float = 5.0,
) -> threading.Thread:
    """Start a daemon thread that consumes events, reconnecting if the broker drops.

    A named queue is durable and shared: messages wait for the service while it
    is down, and several instances split the work. `queue_name=None` declares a
    private queue that is deleted when this process disconnects, so every
    instance receives every event — right for live fan-out such as a dashboard,
    wrong for work that must happen exactly once.
    """

    def _consume_once() -> None:
        connection = pika.BlockingConnection(pika.URLParameters(url))
        try:
            channel = connection.channel()
            declare_exchange(channel)
            if queue_name is None:
                declared = channel.queue_declare(
                    queue="", exclusive=True, auto_delete=True
                )
                queue = declared.method.queue
            else:
                channel.queue_declare(queue=queue_name, durable=True)
                queue = queue_name
            for routing_key in routing_keys:
                channel.queue_bind(
                    queue=queue, exchange=EVENT_EXCHANGE, routing_key=routing_key
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
                    logger.exception("event handler failed for %s", method.routing_key)
                    ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

            channel.basic_consume(queue=queue, on_message_callback=_callback)
            logger.info("consumer started on queue=%s keys=%s", queue, routing_keys)
            channel.start_consuming()
        finally:
            if connection.is_open:
                connection.close()

    def _run_forever() -> None:
        while True:
            try:
                _consume_once()
            except Exception:
                logger.warning(
                    "consumer for %s lost its broker connection; retrying in %.0fs",
                    queue_name or routing_keys,
                    reconnect_delay_seconds,
                    exc_info=True,
                )
            time.sleep(reconnect_delay_seconds)

    thread = threading.Thread(
        target=_run_forever, name=f"rmq-{queue_name or 'fanout'}", daemon=True
    )
    thread.start()
    return thread
