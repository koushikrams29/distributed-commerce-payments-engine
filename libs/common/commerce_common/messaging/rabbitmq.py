"""RabbitMQ helpers shared across services.

Delivery is at-least-once: a message can be handled more than once (after a
crash, or a retry whose acknowledgement was lost), so every handler must be
idempotent.

A failing message on a named queue is retried with increasing delays, then
parked on a dead-letter queue instead of being redelivered forever:

    payment.events ──fail──▶ payment.events.retry.2s  ──after 2s──▶ payment.events
                   ──fail──▶ payment.events.retry.10s ──after 10s─▶ payment.events
                   ──fail──▶ payment.events.retry.30s ──after 30s─▶ payment.events
                   ──fail──▶ payment.events.dlq   (kept until replayed or purged)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pika
from pika.adapters.blocking_connection import BlockingChannel

from commerce_common.events.types import EVENT_EXCHANGE

logger = logging.getLogger(__name__)

EventHandler = Callable[[str, dict[str, Any]], None]

RETRY_COUNT_HEADER = "x-retry-count"
# Retried and dead-lettered messages travel through the default exchange,
# addressed by queue name, so the event type is carried here instead.
ORIGINAL_ROUTING_KEY_HEADER = "x-original-routing-key"
LAST_ERROR_HEADER = "x-last-error"
DEAD_LETTERED_AT_HEADER = "x-dead-lettered-at"

DEFAULT_RETRY_DELAYS_SECONDS: tuple[float, ...] = (2.0, 10.0, 30.0)
_MAX_ERROR_LENGTH = 500


class NonRetryableError(Exception):
    """Raise from a handler when retrying cannot help (e.g. an invalid payload).

    The message goes straight to the dead-letter queue.
    """


def declare_exchange(channel: BlockingChannel) -> None:
    channel.exchange_declare(
        exchange=EVENT_EXCHANGE, exchange_type="topic", durable=True
    )


def retry_queue_name(queue_name: str, delay_seconds: float) -> str:
    # The delay is part of the name because RabbitMQ refuses to redeclare a
    # queue with different arguments: changing a delay creates a new queue
    # rather than crashing every consumer on startup.
    milliseconds = round(delay_seconds * 1000)
    suffix = f"{milliseconds // 1000}s" if milliseconds % 1000 == 0 else f"{milliseconds}ms"
    return f"{queue_name}.retry.{suffix}"


def dead_letter_queue_name(queue_name: str) -> str:
    return f"{queue_name}.dlq"


def declare_work_queue(
    channel: BlockingChannel,
    queue_name: str,
    routing_keys: Sequence[str],
    retry_delays_seconds: Sequence[float] = DEFAULT_RETRY_DELAYS_SECONDS,
) -> None:
    """Declare a durable work queue plus its retry and dead-letter queues."""
    declare_exchange(channel)
    channel.queue_declare(queue=queue_name, durable=True)
    for routing_key in routing_keys:
        channel.queue_bind(
            queue=queue_name, exchange=EVENT_EXCHANGE, routing_key=routing_key
        )
    for delay in retry_delays_seconds:
        # No consumer reads a retry queue. Messages sit out their TTL, then
        # RabbitMQ dead-letters them back to the work queue. One TTL per queue
        # avoids the head-of-line blocking of per-message expirations.
        channel.queue_declare(
            queue=retry_queue_name(queue_name, delay),
            durable=True,
            arguments={
                "x-message-ttl": round(delay * 1000),
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": queue_name,
            },
        )
    channel.queue_declare(queue=dead_letter_queue_name(queue_name), durable=True)


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


@dataclass
class Consumer:
    """Handle to a running consumer thread."""

    thread: threading.Thread
    _stopping: threading.Event = field(repr=False)

    def stop(self, timeout: float | None = 10.0) -> None:
        """Finish the in-flight message, close the connection and end the thread."""
        self._stopping.set()
        self.thread.join(timeout)


def run_consumer(
    *,
    url: str,
    queue_name: str | None,
    routing_keys: list[str],
    handler: EventHandler,
    retry_delays_seconds: Sequence[float] = DEFAULT_RETRY_DELAYS_SECONDS,
    reconnect_delay_seconds: float = 5.0,
) -> Consumer:
    """Consume events on a daemon thread, reconnecting if the broker drops.

    A named queue is durable and shared: messages wait while the service is
    down, several instances split the work, and failures are retried then
    dead-lettered. `queue_name=None` declares a private queue that is deleted
    when this process disconnects, so every instance receives every event —
    right for live fan-out such as a dashboard, wrong for work that must
    happen exactly once. Failures there are logged and dropped: the queue
    disappears with the process, so there is nowhere durable to retry from.
    """
    stopping = threading.Event()
    delays = tuple(retry_delays_seconds)

    def _consume_once() -> None:
        connection = pika.BlockingConnection(pika.URLParameters(url))
        try:
            channel = connection.channel()
            if queue_name is None:
                declare_exchange(channel)
                declared = channel.queue_declare(
                    queue="", exclusive=True, auto_delete=True
                )
                queue = declared.method.queue
                for routing_key in routing_keys:
                    channel.queue_bind(
                        queue=queue, exchange=EVENT_EXCHANGE, routing_key=routing_key
                    )
                callback = _fanout_callback(handler)
            else:
                declare_work_queue(channel, queue_name, routing_keys, delays)
                # Confirms make basic_publish wait for the broker to accept a
                # retry/dead-letter copy before the original is acknowledged.
                channel.confirm_delivery()
                queue = queue_name
                callback = _work_callback(handler, queue_name, delays)

            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue=queue, on_message_callback=callback)
            logger.info("consumer started on queue=%s keys=%s", queue, routing_keys)
            while not stopping.is_set():
                connection.process_data_events(time_limit=1)
        finally:
            if connection.is_open:
                connection.close()

    def _run_forever() -> None:
        while not stopping.is_set():
            try:
                _consume_once()
            except Exception:
                logger.warning(
                    "consumer for %s lost its broker connection; retrying in %.0fs",
                    queue_name or routing_keys,
                    reconnect_delay_seconds,
                    exc_info=True,
                )
            stopping.wait(reconnect_delay_seconds)

    thread = threading.Thread(
        target=_run_forever, name=f"rmq-{queue_name or 'fanout'}", daemon=True
    )
    thread.start()
    return Consumer(thread=thread, _stopping=stopping)


def _work_callback(
    handler: EventHandler, queue_name: str, delays: tuple[float, ...]
) -> Callable[..., None]:
    def callback(
        channel: BlockingChannel,
        method: pika.spec.Basic.Deliver,
        properties: pika.spec.BasicProperties,
        body: bytes,
    ) -> None:
        headers = dict(properties.headers or {})
        routing_key = str(headers.get(ORIGINAL_ROUTING_KEY_HEADER) or method.routing_key)
        retries = int(headers.get(RETRY_COUNT_HEADER, 0))

        def forward(target_queue: str, extra_headers: dict[str, Any]) -> None:
            # If this publish fails, the exception propagates, the original is
            # never acked, and the broker redelivers it after reconnecting.
            channel.basic_publish(
                exchange="",
                routing_key=target_queue,
                body=body,
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type=properties.content_type or "application/json",
                    message_id=properties.message_id,
                    headers={
                        **headers,
                        ORIGINAL_ROUTING_KEY_HEADER: routing_key,
                        **extra_headers,
                    },
                ),
                mandatory=True,
            )

        def dead_letter(error: str) -> None:
            logger.error(
                "dead-lettering %s from %s after %d retries: %s",
                routing_key, queue_name, retries, error,
            )
            forward(
                dead_letter_queue_name(queue_name),
                {
                    RETRY_COUNT_HEADER: retries,
                    LAST_ERROR_HEADER: error,
                    DEAD_LETTERED_AT_HEADER: datetime.now(UTC).isoformat(),
                },
            )

        try:
            payload = _decode(body)
        except NonRetryableError as exc:
            dead_letter(_describe(exc))
            channel.basic_ack(delivery_tag=method.delivery_tag)
            return

        try:
            handler(routing_key, payload)
        except NonRetryableError as exc:
            dead_letter(_describe(exc))
        except Exception as exc:
            if retries < len(delays):
                delay = delays[retries]
                logger.warning(
                    "handler for %s on %s failed (retry %d/%d in %gs)",
                    routing_key, queue_name, retries + 1, len(delays), delay,
                    exc_info=True,
                )
                forward(
                    retry_queue_name(queue_name, delay),
                    {RETRY_COUNT_HEADER: retries + 1, LAST_ERROR_HEADER: _describe(exc)},
                )
            else:
                logger.exception("handler for %s on %s failed", routing_key, queue_name)
                dead_letter(_describe(exc))
        channel.basic_ack(delivery_tag=method.delivery_tag)

    return callback


def _fanout_callback(handler: EventHandler) -> Callable[..., None]:
    def callback(
        channel: BlockingChannel,
        method: pika.spec.Basic.Deliver,
        _properties: pika.spec.BasicProperties,
        body: bytes,
    ) -> None:
        try:
            handler(method.routing_key, _decode(body))
        except Exception:
            logger.exception("dropping %s after handler failure", method.routing_key)
        channel.basic_ack(delivery_tag=method.delivery_tag)

    return callback


def _decode(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise NonRetryableError(f"body is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise NonRetryableError("body is not a JSON object")
    return payload


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:_MAX_ERROR_LENGTH]
