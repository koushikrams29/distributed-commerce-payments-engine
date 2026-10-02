import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from commerce_common.auth import TokenError, decode_access_token

from app.core.config import settings
from app.core.http import get_http_client
from app.services.proxy_service import (
    UnknownRouteError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
    forward,
)

router = APIRouter(prefix="/api/v1", tags=["proxy"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

PROXIED_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def require_access_token(token: str | None = Depends(oauth2_scheme)) -> None:
    """Reject bad tokens at the edge. Role checks stay in the owning service."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid or missing access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise unauthorized
    try:
        decode_access_token(secret=settings.jwt_secret, token=token)
    except TokenError as exc:
        raise unauthorized from exc


@router.api_route(
    "/{path:path}",
    methods=PROXIED_METHODS,
    dependencies=[Depends(require_access_token)],
)
async def proxy(
    path: str,
    request: Request,
    client: httpx.AsyncClient = Depends(get_http_client),
):
    try:
        return await forward(client, request, path)
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
