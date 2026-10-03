"""Prometheus metrics shared by every service.

Labels are kept to bounded sets (route templates, event types, outcomes) —
never IDs or raw paths — because every distinct label combination is a
separate time series stored by Prometheus.
"""

import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Gauge, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests handled, by route template and status code.",
    ["method", "route", "status"],
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "Time to produce an HTTP response.",
    ["method", "route"],
    buckets=LATENCY_BUCKETS,
)
HTTP_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "HTTP requests currently being handled.",
    ["method"],
)

UNMATCHED_ROUTE = "unmatched"


class PrometheusMiddleware:
    """Records request count, latency and concurrency for every HTTP request."""

    def __init__(self, app: ASGIApp, *, excluded_paths: frozenset[str] = frozenset({"/metrics"})) -> None:
        self.app = app
        self.excluded_paths = excluded_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.excluded_paths:
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        status = 500
        started = time.perf_counter()

        async def send_with_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        HTTP_IN_PROGRESS.labels(method).inc()
        try:
            await self.app(scope, receive, send_with_status)
        finally:
            HTTP_IN_PROGRESS.labels(method).dec()
            route = route_template(scope)
            HTTP_REQUESTS.labels(method, route, str(status)).inc()
            HTTP_DURATION.labels(method, route).observe(time.perf_counter() - started)


def route_template(scope: Scope) -> str:
    """`/orders/{order_id}`, not `/orders/3f2a…` — one series per route, not per order.

    Read after the request: the router records the matched route in the scope,
    including routes reached through included routers. Unknown paths collapse
    into one label so a scanner probing random URLs cannot create unbounded
    series.
    """
    path = getattr(scope.get("route"), "path", None)
    return path if isinstance(path, str) and path else UNMATCHED_ROUTE


def metrics_endpoint(_request: Request) -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
