import asyncio
import contextlib
import json
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.requests import HTTPConnection

from commerce_common.auth import AccessTokenPayload, Role, TokenError, decode_access_token

from app.core.config import settings
from app.realtime.hub import OVERFLOW, DashboardHub, Subscription

router = APIRouter(tags=["dashboard"])

# Application close codes (4000–4999 are reserved for apps by RFC 6455).
CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403
# Standard "try again later": the client fell too far behind.
CLOSE_TRY_AGAIN_LATER = 1013


def get_hub(connection: HTTPConnection) -> DashboardHub:
    return connection.app.state.dashboard_hub


async def _authenticate(websocket: WebSocket) -> AccessTokenPayload | None:
    """Expect `{"type": "auth", "token": "<access token>"}` as the first frame.

    Browsers cannot set an Authorization header on a WebSocket, and a token in
    the URL would end up in access logs, so it travels as the first message.
    """
    try:
        raw = await asyncio.wait_for(
            websocket.receive_text(), timeout=settings.dashboard_auth_timeout_seconds
        )
        message = json.loads(raw)
        if message.get("type") != "auth":
            raise ValueError("first frame must be auth")
        caller = decode_access_token(
            secret=settings.jwt_secret, token=str(message.get("token", ""))
        )
    except (TimeoutError, ValueError, AttributeError, TokenError):
        await websocket.close(code=CLOSE_UNAUTHENTICATED, reason="authentication required")
        return None
    except WebSocketDisconnect:
        return None

    if caller.role != Role.ADMIN:
        await websocket.close(code=CLOSE_FORBIDDEN, reason="admin only")
        return None
    return caller


async def _send_events(websocket: WebSocket, subscription: Subscription) -> None:
    while True:
        message = await subscription.queue.get()
        if message is OVERFLOW:
            await websocket.close(code=CLOSE_TRY_AGAIN_LATER, reason="client too slow")
            return
        await websocket.send_json(message)


async def _wait_for_disconnect(websocket: WebSocket) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return


async def _expire_with_token(websocket: WebSocket, caller: AccessTokenPayload) -> None:
    """Close when the access token expires; the client reconnects with a fresh one."""
    if caller.expires_at is None:
        await asyncio.Event().wait()
    remaining = (caller.expires_at - datetime.now(UTC)).total_seconds()
    await asyncio.sleep(max(0.0, remaining))
    await websocket.close(code=CLOSE_UNAUTHENTICATED, reason="token expired")


@router.websocket("/ws/dashboard")
async def dashboard_events(websocket: WebSocket) -> None:
    """Live stream of domain events for the admin dashboard (FR-6)."""
    await websocket.accept()
    caller = await _authenticate(websocket)
    if caller is None:
        return

    hub = get_hub(websocket)
    # Subscribe before announcing readiness so no event can slip in between.
    subscription = hub.subscribe()
    try:
        await websocket.send_json({"type": "ready"})
        tasks = {
            asyncio.create_task(_send_events(websocket, subscription)),
            asyncio.create_task(_wait_for_disconnect(websocket)),
            asyncio.create_task(_expire_with_token(websocket, caller)),
        }
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in pending:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        for task in done:
            # A send on a socket the browser already closed is not an error here.
            with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                task.result()
    finally:
        hub.unsubscribe(subscription)
