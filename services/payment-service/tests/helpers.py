import uuid
from decimal import Decimal
from typing import Any

from commerce_common.auth import Role, create_access_token

from app.core.config import settings


def auth_header(*, role: Role = Role.ADMIN) -> dict[str, str]:
    token = create_access_token(
        secret=settings.jwt_secret,
        user_id=uuid.uuid4(),
        role=role,
        expires_minutes=15,
    )
    return {"Authorization": f"Bearer {token}"}


def charge_payload(
    *,
    order_id: uuid.UUID | None = None,
    amount: str = "100.00",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    return {
        "order_id": str(order_id or uuid.uuid4()),
        "amount": amount,
        "idempotency_key": idempotency_key or f"pay-{uuid.uuid4().hex}",
    }
