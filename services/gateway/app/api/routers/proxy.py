import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from commerce_common.auth import AccessTokenPayload, TokenError, decode_access_token

from app.api.rate_limit import get_api_limiter, raise_if_limited
from app.core.config import settings
from app.core.http import get_http_client
from app.services.proxy_service import (
    UnknownRouteError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
    forward,
)
from app.services.rate_limiter import TokenBucketLimiter

router = APIRouter(prefix="/api/v1", tags=["proxy"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

PROXIED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def require_access_token(
    token: str | None = Depends(oauth2_scheme),
) -> AccessTokenPayload:
    """Reject bad tokens at the edge. Role checks stay in the owning service."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid or missing access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise unauthorized
    try:
        return decode_access_token(secret=settings.jwt_secret, token=token)
    except TokenError as exc:
        raise unauthorized from exc


@router.api_route("/{path:path}", methods=PROXIED_METHODS)
async def proxy(
    path: str,
    request: Request,
    caller: AccessTokenPayload = Depends(require_access_token),
    limiter: TokenBucketLimiter | None = Depends(get_api_limiter),
    client: httpx.AsyncClient = Depends(get_http_client),
):
    # Keyed by user, not IP: users behind one office NAT don't share a
    # bucket, and one user can't dodge the limit by switching networks (FR-7).
    rate_limit_headers: dict[str, str] = {}
    if limiter is not None:
        result = await limiter.consume(str(caller.user_id))
        raise_if_limited(result)
        rate_limit_headers = result.headers()

    try:
        response = await forward(client, request, path)
    except UnknownRouteError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "route not found") from exc
    except UpstreamTimeoutError as exc:
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT, f"{exc} service timed out"
        ) from exc
    except UpstreamUnavailableError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"{exc} service unavailable"
        ) from exc

    response.headers.update(rate_limit_headers)
    return response
