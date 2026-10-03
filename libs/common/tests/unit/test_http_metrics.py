import uuid

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from commerce_common.observability import ObservabilitySettings, setup_observability
from commerce_common.observability.metrics import UNMATCHED_ROUTE

SERVICE = f"metrics-test-{uuid.uuid4().hex[:6]}"


def _app() -> FastAPI:
    app = FastAPI()
    # Services declare routes on included routers, which match differently
    # from routes declared on the app itself.
    orders = APIRouter(prefix="/orders")

    @orders.get("/{order_id}")
    def get_order(order_id: str) -> dict[str, str]:
        if order_id == "missing":
            raise HTTPException(status_code=404)
        return {"id": order_id}

    app.include_router(orders)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    setup_observability(app, service_name=SERVICE, settings=ObservabilitySettings())
    return app


client = TestClient(_app())


def _requests(route: str, status: str, method: str = "GET") -> float:
    value = REGISTRY.get_sample_value(
        "http_requests_total", {"method": method, "route": route, "status": status}
    )
    return value or 0.0


def test_requests_are_counted_by_route_template_not_raw_path() -> None:
    before = _requests("/orders/{order_id}", "200")

    client.get(f"/orders/{uuid.uuid4()}")
    client.get(f"/orders/{uuid.uuid4()}")

    assert _requests("/orders/{order_id}", "200") == before + 2


def test_error_status_is_recorded() -> None:
    before = _requests("/orders/{order_id}", "404")
    client.get("/orders/missing")
    assert _requests("/orders/{order_id}", "404") == before + 1


def test_unknown_paths_share_one_series() -> None:
    before = _requests(UNMATCHED_ROUTE, "404")

    client.get("/wp-admin/setup.php")
    client.get(f"/random/{uuid.uuid4()}")

    assert _requests(UNMATCHED_ROUTE, "404") == before + 2


def test_latency_is_observed() -> None:
    labels = {"method": "GET", "route": "/health"}
    before = REGISTRY.get_sample_value("http_request_duration_seconds_count", labels) or 0.0
    client.get("/health")
    assert REGISTRY.get_sample_value("http_request_duration_seconds_count", labels) == before + 1


def test_metrics_endpoint_serves_the_prometheus_text_format() -> None:
    client.get("/health")

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "http_requests_total" in response.text
    assert 'route="/metrics"' not in response.text
