import asyncio
from collections.abc import Callable, Iterator
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider

from commerce_common.auth import Role, create_access_token
from commerce_common.messaging.replay import DeadLetterMessage, UnknownQueueError

from app.core.config import settings
from app.core.http import get_http_client
from app.main import app
from app.realtime.events import relay_message
from app.realtime.hub import DashboardHub
from app.services import ops_service

Handler = Callable[[httpx.Request], httpx.Response]


def _auth(role: Role = Role.ADMIN) -> dict[str, str]:
    token = create_access_token(
        secret=settings.jwt_secret, user_id=uuid4(), role=role, expires_minutes=5
    )
    return {"Authorization": f"Bearer {token}"}


class Network:
    """Answers for every downstream service and the broker's management API."""

    def __init__(self) -> None:
        self.routes: dict[str, Handler] = {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for prefix, handler in self.routes.items():
            if str(request.url).startswith(prefix):
                return handler(request)
        return httpx.Response(200, json={"status": "ok"})


@pytest.fixture
def network() -> Network:
    return Network()


@pytest.fixture
def client(network: Network, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(ops_service, "check_gateway_database", lambda: None)
    fake = httpx.AsyncClient(transport=httpx.MockTransport(network))
    app.dependency_overrides[get_http_client] = lambda: fake
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _components(client: TestClient) -> dict[str, dict]:
    response = client.get("/api/v1/ops/health", headers=_auth())
    assert response.status_code == 200
    return {item["name"]: item for item in response.json()["components"]}


class TestHealth:
    def test_reports_every_service_and_the_broker(self, client: TestClient) -> None:
        components = _components(client)

        assert list(components) == [
            "gateway",
            "order-service",
            "inventory-service",
            "payment-service",
            "notification-service",
            "recommendation-service",
            "rabbitmq",
        ]
        assert {item["status"] for item in components.values()} == {"up"}
        assert components["payment-service"]["kind"] == "service"
        assert components["rabbitmq"]["kind"] == "infrastructure"

    def test_a_failing_database_check_is_degraded_not_down(
        self, client: TestClient, network: Network
    ) -> None:
        network.routes[settings.payment_service_url] = lambda _r: httpx.Response(500)

        payment = _components(client)["payment-service"]

        assert payment["status"] == "degraded"
        assert payment["detail"] == "database check failed (HTTP 500)"
        assert payment["latency_ms"] is not None

    @pytest.mark.parametrize(
        ("error", "detail"),
        [
            (httpx.ConnectError("refused"), "unreachable"),
            (httpx.ReadTimeout("slow"), "health check timed out"),
        ],
    )
    def test_a_service_that_does_not_answer_is_down(
        self, client: TestClient, network: Network, error: Exception, detail: str
    ) -> None:
        def fail(request: httpx.Request) -> httpx.Response:
            raise type(error)(str(error), request=request)

        network.routes[settings.order_service_url] = fail

        order = _components(client)["order-service"]

        assert (order["status"], order["detail"]) == ("down", detail)

    def test_a_broker_that_rejects_the_credentials_is_down(
        self, client: TestClient, network: Network
    ) -> None:
        network.routes[settings.rabbitmq_management_url] = lambda _r: httpx.Response(401)

        broker = _components(client)["rabbitmq"]

        assert broker["status"] == "down"
        assert broker["detail"] == "management API rejected the credentials"

    def test_the_gateway_is_degraded_when_its_database_fails(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken() -> None:
            raise RuntimeError("connection refused")

        monkeypatch.setattr(ops_service, "check_gateway_database", broken)

        gateway = _components(client)["gateway"]

        assert (gateway["status"], gateway["detail"]) == ("degraded", "database check failed")


class FakeRedis:
    def __init__(self, *, healthy: bool) -> None:
        self.healthy = healthy

    async def ping(self) -> bool:
        if not self.healthy:
            raise ConnectionError("redis down")
        return True


@pytest.mark.parametrize(("healthy", "status"), [(True, "up"), (False, "down")])
def test_redis_is_checked_when_rate_limiting_uses_it(healthy: bool, status: str) -> None:
    fake = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={}))
    )

    health = asyncio.run(
        ops_service.system_health(
            fake, redis=FakeRedis(healthy=healthy), check_database=lambda: None
        )
    )

    redis = next(item for item in health.components if item.name == "redis")
    assert redis.status == status


QUEUES = [
    {"name": "payment.events", "messages_ready": 3, "messages_unacknowledged": 1,
     "consumers": 2, "message_stats": {"publish_details": {"rate": 1.5},
                                       "deliver_get_details": {"rate": 1.25}}},
    {"name": "payment.events.retry.2s", "messages": 2},
    {"name": "payment.events.retry.10s", "messages": 1},
    {"name": "payment.events.dlq", "messages": 4},
    {"name": "order.events", "messages_ready": 0, "messages_unacknowledged": 0, "consumers": 1},
    {"name": "order.events.dlq", "messages": 0},
    {"name": "amq.gen-JzTY20BRgKO-HjmUJj0wLg", "messages": 0},
]


class TestQueues:
    def test_groups_each_work_queue_with_its_retry_and_dead_letter_queues(
        self, client: TestClient, network: Network
    ) -> None:
        network.routes[f"{settings.rabbitmq_management_url}/api/queues"] = (
            lambda _r: httpx.Response(200, json=QUEUES)
        )

        body = client.get("/api/v1/ops/queues", headers=_auth()).json()

        assert body["queues"] == [
            {"name": "order.events", "ready": 0, "unacknowledged": 0, "consumers": 1,
             "retrying": 0, "dead_lettered": 0, "publish_rate": 0.0, "deliver_rate": 0.0},
            {"name": "payment.events", "ready": 3, "unacknowledged": 1, "consumers": 2,
             "retrying": 3, "dead_lettered": 4, "publish_rate": 1.5, "deliver_rate": 1.25},
        ]

    def test_signs_in_with_the_amqp_credentials(
        self, client: TestClient, network: Network
    ) -> None:
        network.routes[f"{settings.rabbitmq_management_url}/api/queues"] = (
            lambda _r: httpx.Response(200, json=[])
        )

        client.get("/api/v1/ops/queues", headers=_auth())

        sent = network.requests[-1]
        assert sent.headers["authorization"].startswith("Basic ")
        assert "columns=" in str(sent.url)

    def test_an_unreachable_broker_is_a_503(self, client: TestClient, network: Network) -> None:
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        network.routes[settings.rabbitmq_management_url] = refuse

        response = client.get("/api/v1/ops/queues", headers=_auth())

        assert response.status_code == 503
        assert response.json()["detail"] == "management API unreachable"


def _message(body: bytes, **overrides: object) -> DeadLetterMessage:
    fields: dict[str, object] = {
        "body": body,
        "routing_key": "charge.requested",
        "retry_count": 3,
        "last_error": "OperationalError: database unavailable",
        "dead_lettered_at": "2026-10-04T07:12:09+00:00",
        "message_id": None,
    }
    fields.update(overrides)
    return DeadLetterMessage(**fields)  # type: ignore[arg-type]


class TestDeadLetters:
    def test_shows_the_waiting_messages_with_why_they_failed(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        peeked: list[tuple[str, int]] = []

        def peek(url: str, queue: str, *, limit: int) -> list[DeadLetterMessage]:
            peeked.append((queue, limit))
            return [
                _message(b'{"order_id": "9b2f6c1e", "amount": "59.00"}'),
                _message(b"{not json", routing_key=None, retry_count=None),
            ]

        monkeypatch.setattr(ops_service, "count_dead_letters", lambda url, queue: 7)
        monkeypatch.setattr(ops_service, "peek_dead_letters", peek)

        body = client.get(
            "/api/v1/ops/dead-letters/payment.events", params={"limit": 2}, headers=_auth()
        ).json()

        assert peeked == [("payment.events", 2)]
        assert body["total"] == 7
        first, second = body["messages"]
        assert first["payload"] == {"order_id": "9b2f6c1e", "amount": "59.00"}
        assert first["order_id"] == "9b2f6c1e"
        assert first["last_error"] == "OperationalError: database unavailable"
        assert second["payload"] == "{not json"
        assert second["order_id"] is None

    def test_a_json_body_that_is_not_an_object_is_shown_as_text(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(ops_service, "count_dead_letters", lambda url, queue: 1)
        monkeypatch.setattr(
            ops_service, "peek_dead_letters", lambda url, queue, limit: [_message(b"[1, 2]")]
        )

        body = client.get("/api/v1/ops/dead-letters/order.events", headers=_auth()).json()

        assert body["messages"][0]["payload"] == "[1, 2]"

    def test_an_unknown_queue_is_a_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def missing(url: str, queue: str) -> int:
            raise UnknownQueueError(queue)

        monkeypatch.setattr(ops_service, "count_dead_letters", missing)

        response = client.get("/api/v1/ops/dead-letters/nope.events", headers=_auth())

        assert response.status_code == 404

    @pytest.mark.parametrize("queue", ["UPPER.events", "-leading.events", "a" * 202])
    def test_a_malformed_queue_name_never_reaches_the_broker(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, queue: str
    ) -> None:
        monkeypatch.setattr(ops_service, "count_dead_letters", pytest.fail)

        response = client.get(f"/api/v1/ops/dead-letters/{queue}", headers=_auth())

        assert response.status_code == 404


class TestReplay:
    def test_replays_up_to_the_limit(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, int | None]] = []

        def replay(url: str, queue: str, *, limit: int | None) -> int:
            calls.append((queue, limit))
            return 2

        monkeypatch.setattr(ops_service, "replay_dead_letters", replay)

        response = client.post(
            "/api/v1/ops/dead-letters/payment.events/replay",
            json={"limit": 2},
            headers=_auth(),
        )

        assert response.status_code == 200
        assert response.json() == {"queue": "payment.events", "replayed": 2}
        assert calls == [("payment.events", 2)]

    def test_without_a_body_replays_everything(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[int | None] = []

        def replay(url: str, queue: str, *, limit: int | None) -> int:
            calls.append(limit)
            return 0

        monkeypatch.setattr(ops_service, "replay_dead_letters", replay)

        client.post("/api/v1/ops/dead-letters/payment.events/replay", headers=_auth())

        assert calls == [None]

    def test_an_unknown_queue_is_a_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def missing(url: str, queue: str, *, limit: int | None) -> int:
            raise UnknownQueueError(queue)

        monkeypatch.setattr(ops_service, "replay_dead_letters", missing)

        response = client.post(
            "/api/v1/ops/dead-letters/nope.events/replay", headers=_auth()
        )

        assert response.status_code == 404


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/ops/health"),
        ("GET", "/api/v1/ops/queues"),
        ("GET", "/api/v1/ops/dead-letters/payment.events"),
        ("POST", "/api/v1/ops/dead-letters/payment.events/replay"),
    ],
)
def test_ops_views_are_admin_only(
    client: TestClient, network: Network, method: str, path: str
) -> None:
    anonymous = client.request(method, path)
    shopper = client.request(method, path, headers=_auth(Role.SHOPPER))

    assert anonymous.status_code == 401
    assert shopper.status_code == 403
    assert network.requests == []


def _relayed(publish: Callable[[DashboardHub], None]) -> dict:
    async def run() -> dict:
        hub = DashboardHub()
        subscription = hub.subscribe()
        publish(hub)
        return await asyncio.wait_for(subscription.queue.get(), timeout=1)

    return asyncio.run(run())


class TestLiveEventTrace:
    def test_events_carry_the_trace_that_published_them(self) -> None:
        tracer = TracerProvider().get_tracer("test")
        trace_ids: list[str] = []

        def publish(hub: DashboardHub) -> None:
            with tracer.start_as_current_span("charge.requested process") as span:
                relay_message(hub, "charge.requested", {"order_id": "o-1"})
                trace_ids.append(format(span.get_span_context().trace_id, "032x"))

        message = _relayed(publish)

        assert message["type"] == "charge.requested"
        assert message["data"] == {"order_id": "o-1"}
        assert message["trace_id"] == trace_ids[0]

    def test_without_a_trace_the_id_is_null(self) -> None:
        message = _relayed(lambda hub: relay_message(hub, "order.paid", {"order_id": "o-1"}))

        assert message["trace_id"] is None
