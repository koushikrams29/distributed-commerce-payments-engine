import uuid
from typing import Any


def fresh_key() -> str:
    """An idempotency key that has never been used before.

    Keys are single-use for life, so a hardcoded one would make a test pass on
    the first run and fail on every run after that.
    """
    return f"test-key-{uuid.uuid4()}"


def order_payload(key: str, qty: int = 2) -> dict[str, Any]:
    return {
        "user_id": str(uuid.uuid4()),
        "idempotency_key": key,
        "items": [{"product_id": str(uuid.uuid4()), "qty": qty}],
    }
