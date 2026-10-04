from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

HealthStatus = Literal["up", "degraded", "down"]


class ComponentHealth(BaseModel):
    name: str
    kind: Literal["service", "infrastructure"]
    status: HealthStatus
    # Why it isn't "up", in operator terms; None when healthy.
    detail: str | None = None
    latency_ms: float | None = None


class SystemHealth(BaseModel):
    components: list[ComponentHealth]
    checked_at: datetime


class QueueStats(BaseModel):
    """A service's work queue together with its retry and dead-letter queues."""

    name: str
    ready: int
    unacknowledged: int
    consumers: int
    # Messages sitting out a retry delay, across every retry queue.
    retrying: int
    dead_lettered: int
    publish_rate: float
    deliver_rate: float


class QueueOverview(BaseModel):
    queues: list[QueueStats]
    checked_at: datetime


class DeadLetter(BaseModel):
    routing_key: str | None
    payload: dict[str, Any] | str
    order_id: str | None
    retry_count: int | None
    last_error: str | None
    dead_lettered_at: str | None
    message_id: str | None


class DeadLetterPage(BaseModel):
    queue: str
    total: int
    messages: list[DeadLetter]


class ReplayRequest(BaseModel):
    # None replays everything waiting.
    limit: int | None = Field(default=None, ge=1, le=1000)


class ReplayResult(BaseModel):
    queue: str
    replayed: int
