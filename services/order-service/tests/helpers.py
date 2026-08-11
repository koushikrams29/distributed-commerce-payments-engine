import uuid
from typing import Any

from commerce_common.auth import Role, create_access_token

from app.core.config import settings


def fresh_key() -> str:
    """An idempotency key that has never been used before.

    Keys are single-use for life per user, so a hardcoded one would make a
    test pass on the first run and fail on every run after that.
    """
    return f"test-key-{uuid.uuid4()}"


def order_payload(key: str, qty: int = 2) -> dict[str, Any]:
    return {
        "idempotency_key": key,
        "items": [{"product_id": str(uuid.uuid4()), "qty": qty}],
    }


def auth_header(
    *,
    user_id: uuid.UUID | None = None,
    role: Role = Role.SHOPPER,
) -> dict[str, str]:
    """Bearer header with a freshly signed access token for tests."""
    token = create_access_token(
        secret=settings.jwt_secret,
        user_id=user_id or uuid.uuid4(),
        role=role,
        expires_minutes=15,
    )
    return {"Authorization": f"Bearer {token}"}
