import json
from collections.abc import Callable, Iterator
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from commerce_common.auth import Role, create_access_token

from app.core.config import settings
from app.core.http import get_http_client
from app.main import app

Handler = Callable[[httpx.Request], httpx.Response]


def _token(role: Role = Role.SHOPPER) -> str:
    return create_access_token(
        secret=settings.jwt_secret,
        user_id=uuid4(),
        role=role,
        expires_minutes=5,
    )


def _auth(role: Role = Role.SHOPPER) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(role)}"}


class Upstream:
    """Stands in for every downstream service; records what the gateway sent."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.handler: Handler = lambda _request: httpx.Response(200, json={})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


@pytest.fixture
def upstream() -> Upstream:
    return Upstream()


@pytest.fixture
def client(upstream: Upstream) -> Iterator[TestClient]:
    fake = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    app.dependency_overrides[get_http_client] = lambda: fake
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_forwards_method_path_query_body_and_token(
    client: TestClient, upstream: Upstream
) -> None:
    upstream.handler = lambda _request: httpx.Response(
        201, json={"order_id": "abc", "status": "pending"}
    )
    headers = _auth()
    body = {"items": [{"product_id": "p1", "qty": 2}], "idempotency_key": "k1"}

    response = client.post(
        "/api/v1/orders?source=web", json=body, headers=headers
    )

    assert response.status_code == 201
    assert response.json() == {"order_id": "abc", "status": "pending"}

    sent = upstream.requests[0]
    assert sent.method == "POST"
    assert str(sent.url) == f"{settings.order_service_url}/orders?source=web"
    assert json.loads(sent.content) == body
    assert sent.headers["authorization"] == headers["Authorization"]


@pytest.mark.parametrize(
    ("path", "base_url_setting"),
    [
        ("orders/123", "order_service_url"),
        ("products/p1", "inventory_service_url"),
        ("reservations/o1/release", "inventory_service_url"),
        ("charges", "payment_service_url"),
        ("payments/o1", "payment_service_url"),
        ("recommendations/p1", "recommendation_service_url"),
    ],
)
def test_routes_each_resource_to_its_owning_service(
    client: TestClient, upstream: Upstream, path: str, base_url_setting: str
) -> None:
    client.get(f"/api/v1/{path}", headers=_auth(Role.ADMIN))

    base_url = getattr(settings, base_url_setting)
    assert str(upstream.requests[0].url) == f"{base_url}/{path}"


def test_passes_downstream_errors_through_unchanged(
    client: TestClient, upstream: Upstream
) -> None:
    upstream.handler = lambda _request: httpx.Response(
        403, json={"detail": "admin only"}
    )

    response = client.get("/api/v1/orders", headers=_auth())

    assert response.status_code == 403
    assert response.json() == {"detail": "admin only"}


def test_missing_token_is_rejected_before_reaching_services(
    client: TestClient, upstream: Upstream
) -> None:
    response = client.get("/api/v1/orders/123")

    assert response.status_code == 401
    assert upstream.requests == []


def test_forged_token_is_rejected_before_reaching_services(
    client: TestClient, upstream: Upstream
) -> None:
    forged = create_access_token(
        secret="some-other-secret-at-least-32-characters",
        user_id=uuid4(),
        role=Role.ADMIN,
        expires_minutes=5,
    )

    response = client.get(
        "/api/v1/orders/123", headers={"Authorization": f"Bearer {forged}"}
    )

    assert response.status_code == 401
    assert upstream.requests == []


def test_unknown_resource_returns_404(
    client: TestClient, upstream: Upstream
) -> None:
    response = client.get("/api/v1/unknown/thing", headers=_auth())

    assert response.status_code == 404
    assert upstream.requests == []


@pytest.mark.parametrize(
    "path", ["charges", "reservations", "reservations/o1/release"]
)
@pytest.mark.parametrize("role", [Role.SHOPPER, Role.ADMIN])
def test_internal_commands_are_not_exposed_at_the_public_gateway(
    client: TestClient, upstream: Upstream, path: str, role: Role
) -> None:
    response = client.post(f"/api/v1/{path}", headers=_auth(role))

    assert response.status_code == 404
    assert upstream.requests == []


def test_unreachable_service_returns_502(
    client: TestClient, upstream: Upstream
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    upstream.handler = refuse

    response = client.get("/api/v1/payments/o1", headers=_auth(Role.ADMIN))

    assert response.status_code == 502


def test_slow_service_returns_504(client: TestClient, upstream: Upstream) -> None:
    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    upstream.handler = hang

    response = client.get("/api/v1/orders/123", headers=_auth())

    assert response.status_code == 504
