from app.core.cursors import CursorError, decode_cursor, encode_cursor
from app.models import Order
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest


def _order(*, created_at: datetime | None = None) -> Order:
    return Order(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        idempotency_key="cursor-key",
        status="pending",
        total_amount=Decimal("10.00"),
        created_at=created_at or datetime.now(UTC),
        updated_at=datetime.now(UTC),
        items=[],
    )


def test_cursor_round_trip() -> None:
    order = _order()
    created_at, order_id = decode_cursor(encode_cursor(order))
    assert order_id == order.id
    assert created_at == order.created_at


def test_garbage_cursor_raises() -> None:
    with pytest.raises(CursorError):
        decode_cursor("%%%not-base64%%%")
