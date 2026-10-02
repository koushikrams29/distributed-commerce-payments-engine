import pytest
from redis.asyncio import Redis

from app.services.rate_limiter import TokenBucketLimiter


@pytest.mark.asyncio
async def test_redis_outage_allows_the_request() -> None:
    unreachable = Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.2)
    limiter = TokenBucketLimiter(
        unreachable, name="test", capacity=5, refill_per_second=1
    )

    result = await limiter.consume("user-1")

    assert result.allowed
    assert result.remaining is None
    assert result.headers() == {}
    await unreachable.aclose()


def test_rejects_nonsensical_configuration() -> None:
    redis = Redis()
    with pytest.raises(ValueError):
        TokenBucketLimiter(redis, name="test", capacity=0, refill_per_second=1)
    with pytest.raises(ValueError):
        TokenBucketLimiter(redis, name="test", capacity=5, refill_per_second=0)
