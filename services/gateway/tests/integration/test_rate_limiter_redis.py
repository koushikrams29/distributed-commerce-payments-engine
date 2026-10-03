import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from prometheus_client import REGISTRY
from redis.asyncio import Redis

from app.services.rate_limiter import TokenBucketLimiter


@pytest.fixture(scope="module")
def redis_url() -> Iterator[str]:
    from testcontainers.community.redis import RedisContainer

    with RedisContainer("redis:7-alpine") as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


@pytest_asyncio.fixture
async def redis(redis_url: str) -> AsyncIterator[Redis]:
    client = Redis.from_url(redis_url)
    await client.flushdb()
    yield client
    await client.aclose()


def _limiter(redis: Redis, capacity: int, refill_per_second: float) -> TokenBucketLimiter:
    return TokenBucketLimiter(
        redis, name="test", capacity=capacity, refill_per_second=refill_per_second
    )


@pytest.mark.asyncio
async def test_allows_a_full_burst_then_rejects(redis: Redis) -> None:
    limiter = _limiter(redis, capacity=3, refill_per_second=0.01)

    results = [await limiter.consume("user-1") for _ in range(4)]

    assert [r.allowed for r in results] == [True, True, True, False]
    assert [r.remaining for r in results[:3]] == [2, 1, 0]
    assert results[3].retry_after_seconds >= 1
    assert results[3].headers()["Retry-After"] == str(results[3].retry_after_seconds)


@pytest.mark.asyncio
async def test_decisions_are_counted(redis: Redis) -> None:
    def count(decision: str) -> float:
        return REGISTRY.get_sample_value(
            "gateway_rate_limit_decisions_total", {"limiter": "test", "decision": decision}
        ) or 0.0

    limiter = _limiter(redis, capacity=2, refill_per_second=0.01)
    allowed, limited = count("allowed"), count("limited")

    for _ in range(3):
        await limiter.consume("user-1")

    assert count("allowed") == allowed + 2
    assert count("limited") == limited + 1


@pytest.mark.asyncio
async def test_each_identity_has_its_own_bucket(redis: Redis) -> None:
    limiter = _limiter(redis, capacity=1, refill_per_second=0.01)

    assert (await limiter.consume("user-1")).allowed
    assert not (await limiter.consume("user-1")).allowed
    assert (await limiter.consume("user-2")).allowed


@pytest.mark.asyncio
async def test_tokens_refill_over_time(redis: Redis) -> None:
    limiter = _limiter(redis, capacity=1, refill_per_second=10)

    assert (await limiter.consume("user-1")).allowed
    assert not (await limiter.consume("user-1")).allowed

    await asyncio.sleep(0.25)

    assert (await limiter.consume("user-1")).allowed


@pytest.mark.asyncio
async def test_concurrent_requests_cannot_overspend_the_bucket(redis: Redis) -> None:
    limiter = _limiter(redis, capacity=10, refill_per_second=0.001)

    results = await asyncio.gather(*(limiter.consume("user-1") for _ in range(50)))

    assert sum(r.allowed for r in results) == 10


@pytest.mark.asyncio
async def test_idle_buckets_expire(redis: Redis) -> None:
    limiter = _limiter(redis, capacity=5, refill_per_second=1)

    await limiter.consume("user-1")

    ttl_ms = await redis.pttl("ratelimit:test:user-1")
    assert 0 < ttl_ms <= 6000
