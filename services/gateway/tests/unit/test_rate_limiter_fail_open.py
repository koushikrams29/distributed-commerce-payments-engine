import pytest
from prometheus_client import REGISTRY
from redis.asyncio import Redis

from app.services.rate_limiter import TokenBucketLimiter


def _fail_open_count() -> float:
    return REGISTRY.get_sample_value(
        "gateway_rate_limit_decisions_total", {"limiter": "test", "decision": "fail_open"}
    ) or 0.0


@pytest.mark.asyncio
async def test_redis_outage_allows_the_request() -> None:
    unreachable = Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.2)
    limiter = TokenBucketLimiter(
        unreachable, name="test", capacity=5, refill_per_second=1
    )
    before = _fail_open_count()

    result = await limiter.consume("user-1")

    assert result.allowed
    assert result.remaining is None
    assert result.headers() == {}
    # Visible on a dashboard: otherwise a Redis outage silently disables limiting.
    assert _fail_open_count() == before + 1
    await unreachable.aclose()


def test_rejects_nonsensical_configuration() -> None:
    redis = Redis()
    with pytest.raises(ValueError):
        TokenBucketLimiter(redis, name="test", capacity=0, refill_per_second=1)
    with pytest.raises(ValueError):
        TokenBucketLimiter(redis, name="test", capacity=5, refill_per_second=0)
