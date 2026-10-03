"""Gateway metrics: per-service upstream outcomes and dashboard connection accounting."""

import asyncio
from collections.abc import Callable, Iterator
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from commerce_common.auth import Role, create_access_token

from app.core.config import settings
from app.core.http import get_http_client
from app.main import app
from app.realtime.hub import OVERFLOW, DashboardHub

Handler = Callable[[httpx.Request], httpx.Response]


def _auth() -> dict[str, str]:
    token = create_access_token(
        secret=settings.jwt_secret, user_id=uuid4(), role=Role.ADMIN, expires_minutes=5
    )
    return {"Authorization": f"Bearer {token}"}


def _upstream(upstream: str, outcome: str) -> float:
    return REGISTRY.get_sample_value(
        "gateway_upstream_requests_total", {"upstream": upstream, "outcome": outcome}
    ) or 0.0


def _sample(name: str) -> float:
    return REGISTRY.get_sample_value(name) or 0.0


@pytest.fixture
def respond_with() -> list[Handler]:
    return [lambda _request: httpx.Response(200, json={})]


@pytest.fixture
def client(respond_with: list[Handler]) -> Iterator[TestClient]:
    fake = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: respond_with[0](request))
    )
    app.dependency_overrides[get_http_client] = lambda: fake
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_upstream_responses_are_counted_per_service_and_status(
    client: TestClient, respond_with: list[Handler]
) -> None:
    respond_with[0] = lambda _request: httpx.Response(201, json={})
    before = _upstream("order-service", "201")
    duration_before = REGISTRY.get_sample_value(
        "gateway_upstream_request_duration_seconds_count", {"upstream": "order-service"}
    ) or 0.0

    client.post("/api/v1/orders", json={}, headers=_auth())

    assert _upstream("order-service", "201") == before + 1
    assert REGISTRY.get_sample_value(
        "gateway_upstream_request_duration_seconds_count", {"upstream": "order-service"}
    ) == duration_before + 1


@pytest.mark.parametrize(
    ("error", "outcome", "status"),
    [
        (httpx.ConnectError, "unavailable", 502),
        (httpx.ReadTimeout, "timeout", 504),
    ],
)
def test_upstream_failures_are_counted_by_kind(
    client: TestClient,
    respond_with: list[Handler],
    error: type[httpx.RequestError],
    outcome: str,
    status: int,
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise error("boom", request=request)

    respond_with[0] = fail
    before = _upstream("payment-service", outcome)

    response = client.get("/api/v1/payments/o1", headers=_auth())

    assert response.status_code == status
    assert _upstream("payment-service", outcome) == before + 1


def test_proxied_requests_share_one_route_label(client: TestClient) -> None:
    order_id = uuid4()
    client.get(f"/api/v1/orders/{order_id}", headers=_auth())

    body = client.get("/metrics").text

    assert 'http_requests_total{method="GET",route="/api/v1/{path:path}",status="200"}' in body
    assert str(order_id) not in body


@pytest.mark.asyncio
async def test_connection_gauge_tracks_subscribers_and_ignores_repeat_unsubscribes() -> None:
    hub = DashboardHub()
    before = _sample("gateway_dashboard_connections")

    first, second = hub.subscribe(), hub.subscribe()
    assert _sample("gateway_dashboard_connections") == before + 2

    hub.unsubscribe(first)
    hub.unsubscribe(first)
    assert _sample("gateway_dashboard_connections") == before + 1

    hub.unsubscribe(second)
    assert _sample("gateway_dashboard_connections") == before


@pytest.mark.asyncio
async def test_a_slow_client_is_counted_as_dropped_and_leaves_the_gauge() -> None:
    hub = DashboardHub(max_queue_size=1)
    connections = _sample("gateway_dashboard_connections")
    dropped = _sample("gateway_dashboard_clients_dropped_total")
    subscription = hub.subscribe()

    hub.publish({"type": "a"})
    hub.publish({"type": "b"})
    await asyncio.sleep(0)
    # The socket handler unsubscribes again on its way out.
    hub.unsubscribe(subscription)

    assert subscription.queue.get_nowait() is OVERFLOW
    assert _sample("gateway_dashboard_clients_dropped_total") == dropped + 1
    assert _sample("gateway_dashboard_connections") == connections
