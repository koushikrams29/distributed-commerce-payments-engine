from fastapi import Depends, HTTPException, Request, Response, status

from app.services.rate_limiter import RateLimitResult, TokenBucketLimiter


def get_api_limiter(request: Request) -> TokenBucketLimiter | None:
    return request.app.state.api_limiter


def get_auth_limiter(request: Request) -> TokenBucketLimiter | None:
    return request.app.state.auth_limiter


def client_ip(request: Request) -> str:
    # Behind a load balancer, run uvicorn with --proxy-headers so this is the
    # real client address. Reading X-Forwarded-For here would let any caller
    # pick their own bucket by spoofing the header.
    return request.client.host if request.client else "unknown"


def raise_if_limited(result: RateLimitResult) -> None:
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded",
            headers=result.headers(),
        )


async def limit_auth_attempts(
    request: Request,
    response: Response,
    limiter: TokenBucketLimiter | None = Depends(get_auth_limiter),
) -> None:
    """Keyed by client IP: the caller has no verified identity yet."""
    if limiter is None:
        return
    result = await limiter.consume(client_ip(request))
    raise_if_limited(result)
    response.headers.update(result.headers())
