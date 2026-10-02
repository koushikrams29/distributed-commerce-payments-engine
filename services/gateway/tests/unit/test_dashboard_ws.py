import asyncio
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from commerce_common.auth import Role, create_access_token

from app.core.config import settings
from app.main import app
from app.realtime.hub import OVERFLOW, DashboardHub


def _token(role: Role = Role.ADMIN) -> str:
    return create_access_token(
        secret=settings.jwt_secret, user_id=uuid4(), role=role, expires_minutes=5
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _hub() -> DashboardHub:
    return app.state.dashboard_hub


def test_admin_receives_published_events(client: TestClient) -> None:
    with client.websocket_connect("/ws/dashboard") as ws:
        ws.send_json({"type": "auth", "token": _token()})
        assert ws.receive_json() == {"type": "ready"}

        _hub().publish({"type": "order.status_changed", "data": {"status": "paid"}})

        assert ws.receive_json() == {
            "type": "order.status_changed",
            "data": {"status": "paid"},
        }


def test_every_connected_admin_gets_the_event(client: TestClient) -> None:
    with (
        client.websocket_connect("/ws/dashboard") as first,
        client.websocket_connect("/ws/dashboard") as second,
    ):
        for ws in (first, second):
            ws.send_json({"type": "auth", "token": _token()})
            assert ws.receive_json() == {"type": "ready"}

        _hub().publish({"type": "payment.succeeded", "data": {}})

        assert first.receive_json()["type"] == "payment.succeeded"
        assert second.receive_json()["type"] == "payment.succeeded"


def test_shopper_is_rejected_with_forbidden(client: TestClient) -> None:
    with client.websocket_connect("/ws/dashboard") as ws:
        ws.send_json({"type": "auth", "token": _token(Role.SHOPPER)})
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 4403


@pytest.mark.parametrize(
    "first_frame",
    [
        {"type": "auth", "token": "not-a-jwt"},
        {"type": "hello"},
        {"token": "missing-type"},
    ],
)
def test_bad_first_frame_is_rejected_as_unauthenticated(
    client: TestClient, first_frame: dict
) -> None:
    with client.websocket_connect("/ws/dashboard") as ws:
        ws.send_json(first_frame)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 4401


def test_silent_client_is_closed_after_the_auth_timeout(client: TestClient) -> None:
    with patch.object(settings, "dashboard_auth_timeout_seconds", 0.2):
        with client.websocket_connect("/ws/dashboard") as ws:
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
    assert closed.value.code == 4401


def test_socket_closes_when_the_access_token_expires(client: TestClient) -> None:
    now = datetime.now(UTC)
    short_lived = jwt.encode(
        {
            "sub": str(uuid4()),
            "role": Role.ADMIN.value,
            "typ": "access",
            "iat": now,
            "exp": now + timedelta(seconds=1),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    with client.websocket_connect("/ws/dashboard") as ws:
        ws.send_json({"type": "auth", "token": short_lived})
        assert ws.receive_json() == {"type": "ready"}
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 4401


def test_disconnected_admin_is_unsubscribed(client: TestClient) -> None:
    with client.websocket_connect("/ws/dashboard") as ws:
        ws.send_json({"type": "auth", "token": _token()})
        ws.receive_json()
        assert _hub().subscriber_count == 1

    # The server-side handler finishes on the TestClient's loop thread.
    for _ in range(50):
        if _hub().subscriber_count == 0:
            break
        time.sleep(0.02)
    assert _hub().subscriber_count == 0


def test_slow_subscriber_is_dropped_instead_of_buffering_forever() -> None:
    async def scenario() -> None:
        hub = DashboardHub(max_queue_size=2)
        subscription = hub.subscribe()

        for n in range(3):
            hub.publish({"type": "event", "n": n})
        await asyncio.sleep(0)

        assert hub.subscriber_count == 0
        assert subscription.queue.get_nowait() is OVERFLOW
        assert subscription.queue.empty()

    asyncio.run(scenario())
