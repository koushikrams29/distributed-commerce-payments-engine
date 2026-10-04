"""Inspect dead-lettered messages, and move them back onto their work queue once the cause is fixed.

    python -m commerce_common.messaging.replay payment.events --dry-run
    python -m commerce_common.messaging.replay payment.events --limit 10
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pika
from pika.adapters.blocking_connection import BlockingChannel
from pika.exceptions import ChannelClosedByBroker

from commerce_common.messaging.rabbitmq import (
    DEAD_LETTERED_AT_HEADER,
    LAST_ERROR_HEADER,
    ORIGINAL_ROUTING_KEY_HEADER,
    RETRY_COUNT_HEADER,
    dead_letter_queue_name,
)

REPLAYED_AT_HEADER = "x-replayed-at"
_NOT_FOUND = 404


class UnknownQueueError(LookupError):
    """The work queue has no dead-letter queue (it was never declared)."""


@dataclass(frozen=True)
class DeadLetterMessage:
    body: bytes
    routing_key: str | None
    retry_count: int | None
    last_error: str | None
    dead_lettered_at: str | None
    message_id: str | None


def _dead_letter_queue(channel: BlockingChannel, queue_name: str) -> tuple[str, int]:
    """Name and depth of the queue's dead-letter queue, without creating it."""
    source = dead_letter_queue_name(queue_name)
    try:
        declared = channel.queue_declare(queue=source, passive=True)
    except ChannelClosedByBroker as exc:
        if exc.reply_code == _NOT_FOUND:
            raise UnknownQueueError(queue_name) from exc
        raise
    return source, declared.method.message_count


def count_dead_letters(url: str, queue_name: str) -> int:
    connection = pika.BlockingConnection(pika.URLParameters(url))
    try:
        return _dead_letter_queue(connection.channel(), queue_name)[1]
    finally:
        if connection.is_open:
            connection.close()


def peek_dead_letters(url: str, queue_name: str, *, limit: int) -> list[DeadLetterMessage]:
    """Read up to `limit` dead letters, oldest first, without removing them.

    The messages are fetched unacknowledged and handed straight back, so the
    queue keeps them in the same order (only their redelivered flag changes).
    """
    connection = pika.BlockingConnection(pika.URLParameters(url))
    try:
        channel = connection.channel()
        source, _ = _dead_letter_queue(channel, queue_name)
        messages: list[DeadLetterMessage] = []
        while len(messages) < limit:
            method, properties, body = channel.basic_get(queue=source, auto_ack=False)
            if method is None:
                break
            messages.append(_describe(properties, body))
        if messages:
            channel.basic_nack(delivery_tag=0, multiple=True, requeue=True)
        return messages
    finally:
        if connection.is_open:
            connection.close()


def replay_dead_letters(url: str, queue_name: str, *, limit: int | None = None) -> int:
    """Republish up to `limit` dead letters to `queue_name`; returns how many moved.

    Messages go straight to the work queue (default exchange), not back through
    the topic exchange — that would deliver them to every other service's queue
    as well. Retry bookkeeping is cleared so each message gets a full set of
    retries again.
    """
    connection = pika.BlockingConnection(pika.URLParameters(url))
    moved = 0
    try:
        channel = connection.channel()
        channel.confirm_delivery()
        source, _ = _dead_letter_queue(channel, queue_name)
        while limit is None or moved < limit:
            method, properties, body = channel.basic_get(queue=source, auto_ack=False)
            if method is None:
                break
            headers = {
                key: value
                for key, value in (properties.headers or {}).items()
                if key not in {RETRY_COUNT_HEADER, LAST_ERROR_HEADER, DEAD_LETTERED_AT_HEADER}
            }
            headers[REPLAYED_AT_HEADER] = datetime.now(UTC).isoformat()
            channel.basic_publish(
                exchange="",
                routing_key=queue_name,
                body=body,
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type=properties.content_type,
                    message_id=properties.message_id,
                    headers=headers,
                ),
                mandatory=True,
            )
            # Acked only after the broker confirmed the copy: a crash here can
            # duplicate a message (handlers are idempotent) but never lose one.
            channel.basic_ack(delivery_tag=method.delivery_tag)
            moved += 1
    finally:
        if connection.is_open:
            connection.close()
    return moved


def _describe(properties: pika.BasicProperties, body: bytes) -> DeadLetterMessage:
    headers: dict[str, Any] = dict(properties.headers or {})
    retry_count = headers.get(RETRY_COUNT_HEADER)
    return DeadLetterMessage(
        body=body,
        routing_key=_text(headers.get(ORIGINAL_ROUTING_KEY_HEADER)),
        retry_count=int(retry_count) if retry_count is not None else None,
        last_error=_text(headers.get(LAST_ERROR_HEADER)),
        dead_lettered_at=_text(headers.get(DEAD_LETTERED_AT_HEADER)),
        message_id=properties.message_id,
    )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("queue", help="work queue name, e.g. payment.events")
    parser.add_argument(
        "--url",
        default=os.environ.get("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/"),
        help="AMQP URL (default: $RABBITMQ_URL or local guest)",
    )
    parser.add_argument("--limit", type=int, default=None, help="replay at most N messages")
    parser.add_argument("--dry-run", action="store_true", help="only report how many are waiting")
    args = parser.parse_args(argv)

    try:
        waiting = count_dead_letters(args.url, args.queue)
    except UnknownQueueError:
        print(f"{args.queue} has no dead-letter queue; check the queue name")
        return 1
    if args.dry_run:
        print(f"{dead_letter_queue_name(args.queue)}: {waiting} message(s) waiting")
        return 0
    moved = replay_dead_letters(args.url, args.queue, limit=args.limit)
    print(f"replayed {moved} of {waiting} message(s) to {args.queue}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
