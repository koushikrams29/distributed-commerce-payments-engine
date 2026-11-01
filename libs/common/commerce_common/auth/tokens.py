from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt

from commerce_common.auth.roles import Role

ALGORITHM = "HS256"


class TokenError(Exception):
    """Raised when a token is missing, expired, or forged."""


@dataclass(frozen=True)
class AccessTokenPayload:
    user_id: UUID
    role: Role
    expires_at: datetime | None = None


def create_access_token(
    *,
    secret: str,
    user_id: UUID,
    role: Role,
    expires_minutes: int,
    email: str | None = None,
) -> str:
    """Sign a short-lived access JWT. Anyone with `secret` can verify it.

    `email` is optional display metadata for the console; authorization still
    uses `sub` and `role` only.
    """
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role.value,
        "typ": "access",
        "jti": str(uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    if email:
        payload["email"] = email
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(*, secret: str, token: str) -> AccessTokenPayload:
    """Verify signature + expiry and return the claims we care about."""
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenError("invalid or expired token") from exc

    if payload.get("typ") != "access":
        raise TokenError("not an access token")

    try:
        user_id = UUID(payload["sub"])
        role = Role(payload["role"])
        expires_at = datetime.fromtimestamp(payload["exp"], UTC)
    except (KeyError, ValueError, TypeError) as exc:
        raise TokenError("malformed token claims") from exc

    return AccessTokenPayload(user_id=user_id, role=role, expires_at=expires_at)
