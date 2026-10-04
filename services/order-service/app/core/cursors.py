"""Opaque cursors for keyset pagination of orders."""

from __future__ import annotations

from commerce_common.pagination import CursorError, decode_cursor
from commerce_common.pagination import encode_cursor as _encode_cursor

from app.models import Order

__all__ = ["CursorError", "decode_cursor", "encode_cursor"]


def encode_cursor(order: Order) -> str:
    return _encode_cursor(order.created_at, order.id)
