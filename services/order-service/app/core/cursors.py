"""Opaque cursors for keyset pagination of orders."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime

from app.models import Order


class CursorError(ValueError):
    """Raised when a client sends a malformed cursor."""


def encode_cursor(order: Order) -> str:
    payload = {
        "created_at": order.created_at.isoformat(),
        "id": str(order.id),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        created_at = datetime.fromisoformat(payload["created_at"])
        order_id = uuid.UUID(payload["id"])
    except (KeyError, ValueError, json.JSONDecodeError, UnicodeError) as exc:
        raise CursorError("invalid cursor") from exc
    return created_at, order_id
