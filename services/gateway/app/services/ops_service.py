"""What the admin console needs to judge whether the system is healthy.

Health and queue numbers are read live from each dependency. Nothing is cached:
an operator looking at an incident needs the current state, and every call is
cheap.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx
from redis.asyncio import Redis
from sqlalchemy import text

from commerce_common.messaging.rabbitmq import dead_letter_queue_name
from commerce_common.messaging.replay import (
    DeadLetterMessage,
    count_dead_letters,
    peek_dead_letters,
    replay_dead_letters,
)

from app.core.config import settings
from app.core.db import SessionLocal
from app.schemas.ops import (
    ComponentHealth,
    DeadLetter,
    DeadLetterPage,
    QueueOverview,
    QueueStats,
    SystemHealth,
)

logger = logging.getLogger(__name__)

# Services with an HTTP health endpoint, in the order the console lists them.
SERVICES: tuple[tuple[str, str], ...] = (
    ("order-service", "order_service_url"),
    ("inventory-service", "inventory_service_url"),
    ("payment-service", "payment_service_url"),
    ("notification-service", "notification_service_url"),
    ("recommendation-service", "recommendation_service_url"),
)

# Work queues are named like "payment.events"; anything else is refused before
# it reaches the broker.
_QUEUE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,200}$")
_QUEUE_COLUMNS = ",".join(
    [
        "name",
        "messages",
        "messages_ready",
        "messages_unacknowledged",
        "consumers",
        "message_stats.publish_details.rate",
        "message_stats.deliver_get_details.rate",
    ]
)


class BrokerUnavailableError(Exception):
    """The RabbitMQ management API could not be reached or refused the request."""


def valid_queue_name(name: str) -> bool:
    return bool(_QUEUE_NAME.match(name))


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def check_gateway_database() -> None:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    finally:
        db.close()


async def system_health(
    client: httpx.AsyncClient,
    *,
    redis: Redis | None,
    check_database: Callable[[], None] | None = None,
) -> SystemHealth:
    checks: list[Awaitable[ComponentHealth]] = [
        _check_gateway(check_database or check_gateway_database)
    ]
    checks += [
        _check_service(client, name, getattr(settings, url_setting))
        for name, url_setting in SERVICES
    ]
    checks.append(_check_broker(client))
    if redis is not None:
        checks.append(_check_redis(redis))
    components = await asyncio.gather(*checks)
    return SystemHealth(components=list(components), checked_at=datetime.now(UTC))


async def _check_gateway(check_database: Callable[[], None]) -> ComponentHealth:
    started = time.perf_counter()
    try:
        await asyncio.wait_for(
            asyncio.to_thread(check_database), timeout=settings.ops_health_timeout_seconds
        )
    except Exception:
        logger.warning("gateway database check failed", exc_info=True)
        # This request is being answered, so the process itself is up.
        return ComponentHealth(
            name="gateway",
            kind="service",
            status="degraded",
            detail="database check failed",
            latency_ms=_elapsed_ms(started),
        )
    return ComponentHealth(
        name="gateway", kind="service", status="up", latency_ms=_elapsed_ms(started)
    )


async def _check_service(
    client: httpx.AsyncClient, name: str, base_url: str
) -> ComponentHealth:
    started = time.perf_counter()
    try:
        response = await client.get(
            f"{base_url.rstrip('/')}/health/db",
            timeout=settings.ops_health_timeout_seconds,
        )
    except httpx.TimeoutException:
        return ComponentHealth(
            name=name, kind="service", status="down", detail="health check timed out"
        )
    except httpx.RequestError:
        return ComponentHealth(name=name, kind="service", status="down", detail="unreachable")
    latency = _elapsed_ms(started)
    if response.status_code == 200:
        return ComponentHealth(name=name, kind="service", status="up", latency_ms=latency)
    # The process answered, so only its database check failed.
    return ComponentHealth(
        name=name,
        kind="service",
        status="degraded",
        detail=f"database check failed (HTTP {response.status_code})",
        latency_ms=latency,
    )


async def _check_broker(client: httpx.AsyncClient) -> ComponentHealth:
    started = time.perf_counter()
    try:
        await _management_get(client, "/api/overview", timeout=settings.ops_health_timeout_seconds)
    except BrokerUnavailableError as exc:
        return ComponentHealth(name="rabbitmq", kind="infrastructure", status="down", detail=str(exc))
    return ComponentHealth(
        name="rabbitmq", kind="infrastructure", status="up", latency_ms=_elapsed_ms(started)
    )


async def _check_redis(redis: Redis) -> ComponentHealth:
    started = time.perf_counter()
    try:
        await asyncio.wait_for(redis.ping(), timeout=settings.ops_health_timeout_seconds)
    except Exception:
        # The limiter fails open, so requests still flow; rate limiting is off.
        return ComponentHealth(
            name="redis",
            kind="infrastructure",
            status="down",
            detail="unreachable; rate limiting is failing open",
        )
    return ComponentHealth(
        name="redis", kind="infrastructure", status="up", latency_ms=_elapsed_ms(started)
    )


async def queue_overview(client: httpx.AsyncClient) -> QueueOverview:
    rows = await _management_get(
        client, "/api/queues/%2F", params={"columns": _QUEUE_COLUMNS}
    )
    by_name: dict[str, dict[str, Any]] = {row["name"]: row for row in rows}
    # A work queue is any queue with a dead-letter companion; this skips the
    # retry queues themselves and the gateway's private fan-out queues.
    work_queues = sorted(name for name in by_name if dead_letter_queue_name(name) in by_name)
    queues = []
    for name in work_queues:
        row = by_name[name]
        retry_prefix = f"{name}.retry."
        queues.append(
            QueueStats(
                name=name,
                ready=row.get("messages_ready", 0),
                unacknowledged=row.get("messages_unacknowledged", 0),
                consumers=row.get("consumers", 0),
                retrying=sum(
                    other.get("messages", 0)
                    for other_name, other in by_name.items()
                    if other_name.startswith(retry_prefix)
                ),
                dead_lettered=by_name[dead_letter_queue_name(name)].get("messages", 0),
                publish_rate=_rate(row, "publish_details"),
                deliver_rate=_rate(row, "deliver_get_details"),
            )
        )
    return QueueOverview(queues=queues, checked_at=datetime.now(UTC))


def _rate(row: dict[str, Any], key: str) -> float:
    return float(row.get("message_stats", {}).get(key, {}).get("rate", 0.0))


async def dead_letters(queue: str, *, limit: int) -> DeadLetterPage:
    """Raises UnknownQueueError when the queue has no dead-letter queue."""

    def read() -> tuple[int, list[DeadLetterMessage]]:
        total = count_dead_letters(settings.rabbitmq_url, queue)
        return total, peek_dead_letters(settings.rabbitmq_url, queue, limit=limit)

    total, messages = await asyncio.to_thread(read)
    return DeadLetterPage(
        queue=queue, total=total, messages=[_dead_letter(message) for message in messages]
    )


async def replay(queue: str, *, limit: int | None) -> int:
    """Raises UnknownQueueError when the queue has no dead-letter queue."""
    return await asyncio.to_thread(
        replay_dead_letters, settings.rabbitmq_url, queue, limit=limit
    )


def _dead_letter(message: DeadLetterMessage) -> DeadLetter:
    payload: dict[str, Any] | str
    try:
        decoded = json.loads(message.body)
        payload = decoded if isinstance(decoded, dict) else message.body.decode("utf-8", "replace")
    except (UnicodeDecodeError, ValueError):
        payload = message.body.decode("utf-8", errors="replace")
    order_id = payload.get("order_id") if isinstance(payload, dict) else None
    return DeadLetter(
        routing_key=message.routing_key,
        payload=payload,
        order_id=order_id if isinstance(order_id, str) else None,
        retry_count=message.retry_count,
        last_error=message.last_error,
        dead_lettered_at=message.dead_lettered_at,
        message_id=message.message_id,
    )


def _management_credentials() -> tuple[str, str]:
    parts = urlsplit(settings.rabbitmq_url)
    return unquote(parts.username or "guest"), unquote(parts.password or "guest")


async def _management_get(
    client: httpx.AsyncClient,
    path: str,
    *,
    params: dict[str, str] | None = None,
    timeout: float | None = None,
) -> Any:
    url = f"{settings.rabbitmq_management_url.rstrip('/')}{path}"
    try:
        response = await client.get(
            url,
            params=params,
            auth=_management_credentials(),
            timeout=timeout or settings.proxy_timeout_seconds,
        )
    except httpx.TimeoutException as exc:
        raise BrokerUnavailableError("management API timed out") from exc
    except httpx.RequestError as exc:
        raise BrokerUnavailableError("management API unreachable") from exc
    if response.status_code == 401:
        raise BrokerUnavailableError("management API rejected the credentials")
    if response.status_code != 200:
        raise BrokerUnavailableError(f"management API answered HTTP {response.status_code}")
    return response.json()
