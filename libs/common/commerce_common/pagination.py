"""Opaque cursors for keyset pagination over (created_at, id), newest first.

A cursor names the last row of a page; the next page is every row that sorts
strictly after it. Unlike OFFSET, rows inserted meanwhile never shift a page.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime


class CursorError(ValueError):
    """Raised when a client sends a malformed cursor."""


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    payload = {"created_at": created_at.isoformat(), "id": str(row_id)}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        created_at = datetime.fromisoformat(payload["created_at"])
        row_id = uuid.UUID(payload["id"])
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise CursorError("invalid cursor") from exc
    return created_at, row_id
