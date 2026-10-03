"""Move dead-lettered messages back onto their work queue once the cause is fixed.

    python -m commerce_common.messaging.replay payment.events --dry-run
    python -m commerce_common.messaging.replay payment.events --limit 10
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime

import pika

from commerce_common.messaging.rabbitmq import (
    DEAD_LETTERED_AT_HEADER,
    LAST_ERROR_HEADER,
    RETRY_COUNT_HEADER,
    dead_letter_queue_name,
)

REPLAYED_AT_HEADER = "x-replayed-at"


def count_dead_letters(url: str, queue_name: str) -> int:
    connection = pika.BlockingConnection(pika.URLParameters(url))
    try:
        declared = connection.channel().queue_declare(
            queue=dead_letter_queue_name(queue_name), passive=True
        )
        return declared.method.message_count
    finally:
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
        source = dead_letter_queue_name(queue_name)
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

    waiting = count_dead_letters(args.url, args.queue)
    if args.dry_run:
        print(f"{dead_letter_queue_name(args.queue)}: {waiting} message(s) waiting")
        return 0
    moved = replay_dead_letters(args.url, args.queue, limit=args.limit)
    print(f"replayed {moved} of {waiting} message(s) to {args.queue}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
