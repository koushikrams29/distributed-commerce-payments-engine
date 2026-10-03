import logging
import math
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.metrics import RATE_LIMIT_DECISIONS

logger = logging.getLogger(__name__)

# Runs atomically inside Redis: concurrent requests (even from several gateway
# instances) cannot both read the same token count and both spend it.
# Time comes from the Redis server clock so every gateway instance agrees on it.
TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_per_ms = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])

local now = redis.call('TIME')
local now_ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)

local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil or ts == nil then
    tokens = capacity
    ts = now_ms
end

local elapsed = math.max(0, now_ms - ts)
tokens = math.min(capacity, tokens + elapsed * refill_per_ms)

local allowed = 0
local retry_after_ms = 0
if tokens >= cost then
    tokens = tokens - cost
    allowed = 1
else
    retry_after_ms = math.ceil((cost - tokens) / refill_per_ms)
end

redis.call('HSET', key, 'tokens', tokens, 'ts', now_ms)
-- An idle bucket refills to full after this long, so the key can be dropped.
redis.call('PEXPIRE', key, math.ceil(capacity / refill_per_ms) + 1000)

return {allowed, tostring(tokens), retry_after_ms}
"""


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int | None
    retry_after_seconds: int

    def headers(self) -> dict[str, str]:
        if self.remaining is None:
            return {}
        headers = {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
        }
        if not self.allowed:
            headers["Retry-After"] = str(self.retry_after_seconds)
        return headers


class TokenBucketLimiter:
    """Token bucket per identity, stored as one Redis hash per bucket.

    Each identity gets `capacity` tokens that refill continuously at
    `refill_per_second`. A request spends one token; an empty bucket means 429.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        name: str,
        capacity: int,
        refill_per_second: float,
    ) -> None:
        if capacity < 1 or refill_per_second <= 0:
            raise ValueError("capacity must be >= 1 and refill_per_second > 0")
        self._redis = redis
        self._script = redis.register_script(TOKEN_BUCKET_LUA)
        self.name = name
        self.capacity = capacity
        self.refill_per_second = refill_per_second

    def _key(self, identity: str) -> str:
        return f"ratelimit:{self.name}:{identity}"

    async def consume(self, identity: str, cost: int = 1) -> RateLimitResult:
        try:
            allowed, tokens, retry_after_ms = await self._script(
                keys=[self._key(identity)],
                args=[self.capacity, self.refill_per_second / 1000, cost],
            )
        except RedisError:
            # Fail open: a Redis outage must not take checkout offline.
            # Auth is still enforced here and in every downstream service.
            logger.warning(
                "rate limiter %s unavailable; allowing request", self.name,
                exc_info=True,
            )
            RATE_LIMIT_DECISIONS.labels(self.name, "fail_open").inc()
            return RateLimitResult(
                allowed=True, limit=self.capacity, remaining=None,
                retry_after_seconds=0,
            )

        RATE_LIMIT_DECISIONS.labels(self.name, "allowed" if allowed else "limited").inc()
        return RateLimitResult(
            allowed=bool(allowed),
            limit=self.capacity,
            remaining=math.floor(float(tokens)),
            retry_after_seconds=max(1, math.ceil(int(retry_after_ms) / 1000))
            if not allowed
            else 0,
        )
