from collections.abc import Iterator
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from commerce_common.auth import Role, create_access_token

from app.api.rate_limit import get_api_limiter, get_auth_limiter
from app.core.config import settings
from app.core.http import get_http_client
from app.main import app
from app.services.rate_limiter import RateLimitResult


class FakeLimiter:
    def __init__(self, *, allowed: bool) -> None:
        self.allowed = allowed
        self.identities: list[str] = []

    async def consume(self, identity: str, cost: int = 1) -> RateLimitResult:
        self.identities.append(identity)
        return RateLimitResult(
            allowed=self.allowed,
            limit=20,
            remaining=7 if self.allowed else 0,
            retry_after_seconds=0 if self.allowed else 3,
        )


class Upstream:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return httpx.Response(200, json={"ok": True})


@pytest.fixture
def upstream() -> Upstream:
    return Upstream()


@pytest.fixture
def client(upstream: Upstream) -> Iterator[TestClient]:
    fake_http = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    app.dependency_overrides[get_http_client] = lambda: fake_http
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _auth_header(user_id: UUID) -> dict[str, str]:
    token = create_access_token(
        secret=settings.jwt_secret, user_id=user_id, role=Role.SHOPPER, expires_minutes=5
    )
    return {"Authorization": f"Bearer {token}"}


def test_allowed_request_is_forwarded_with_rate_limit_headers(
    client: TestClient, upstream: Upstream
) -> None:
    limiter = FakeLimiter(allowed=True)
    app.dependency_overrides[get_api_limiter] = lambda: limiter
    user_id = uuid4()

    response = client.get("/api/v1/orders", headers=_auth_header(user_id))

    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == "20"
    assert response.headers["X-RateLimit-Remaining"] == "7"
    assert upstream.calls == 1
    assert limiter.identities == [str(user_id)]


def test_exhausted_bucket_returns_429_without_calling_the_service(
    client: TestClient, upstream: Upstream
) -> None:
    app.dependency_overrides[get_api_limiter] = lambda: FakeLimiter(allowed=False)

    response = client.post("/api/v1/orders", json={}, headers=_auth_header(uuid4()))

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "3"
    assert response.headers["X-RateLimit-Remaining"] == "0"
    assert upstream.calls == 0


def test_invalid_token_is_rejected_before_spending_a_token(
    client: TestClient,
) -> None:
    limiter = FakeLimiter(allowed=True)
    app.dependency_overrides[get_api_limiter] = lambda: limiter

    response = client.get(
        "/api/v1/orders", headers={"Authorization": "Bearer not-a-jwt"}
    )

    assert response.status_code == 401
    assert limiter.identities == []


def test_login_is_limited_per_client_ip_before_touching_the_database(
    client: TestClient,
) -> None:
    limiter = FakeLimiter(allowed=False)
    app.dependency_overrides[get_auth_limiter] = lambda: limiter

    response = client.post(
        "/api/v1/auth/login", data={"username": "a@example.com", "password": "x"}
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "3"
    assert limiter.identities == ["testclient"]
