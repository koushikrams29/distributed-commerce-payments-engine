from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from commerce_common.auth import AccessTokenPayload, Role, TokenError, decode_access_token

from app.core.config import settings

# HTTPBearer (not OAuth2PasswordBearer): login lives on the Gateway, so this
# service only accepts an already-issued Bearer token.
bearer_scheme = HTTPBearer(auto_error=True)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> AccessTokenPayload:
    try:
        return decode_access_token(
            secret=settings.jwt_secret, token=credentials.credentials
        )
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def require_roles(*allowed: Role):
    """FastAPI dependency factory — use on admin-only routes later."""

    def _checker(
        user: AccessTokenPayload = Depends(get_current_user),
    ) -> AccessTokenPayload:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient permissions",
            )
        return user

    return _checker
