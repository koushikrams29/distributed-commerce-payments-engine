import base64
import uuid
from datetime import UTC, datetime

import pytest

from commerce_common.pagination import CursorError, decode_cursor, encode_cursor


def test_a_cursor_round_trips_the_position() -> None:
    created_at = datetime(2026, 10, 4, 9, 30, 15, 123456, tzinfo=UTC)
    row_id = uuid.uuid4()

    assert decode_cursor(encode_cursor(created_at, row_id)) == (created_at, row_id)


def test_a_cursor_is_url_safe() -> None:
    cursor = encode_cursor(datetime.now(UTC), uuid.uuid4())

    assert set(cursor) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=")


def _encoded(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


@pytest.mark.parametrize(
    "cursor",
    [
        "%%%not-base64%%%",
        _encoded("not json"),
        _encoded("[1, 2]"),
        _encoded('{"id": "9b2f6c1e-2d36-4d0e-a5e3-3f0f7f0d8f11"}'),
        _encoded('{"created_at": "yesterday", "id": "9b2f6c1e-2d36-4d0e-a5e3-3f0f7f0d8f11"}'),
        _encoded('{"created_at": "2026-10-04T09:30:15+00:00", "id": "nope"}'),
    ],
)
def test_a_malformed_cursor_is_rejected(cursor: str) -> None:
    with pytest.raises(CursorError):
        decode_cursor(cursor)
