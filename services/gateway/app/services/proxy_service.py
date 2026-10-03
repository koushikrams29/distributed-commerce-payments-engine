import time
from typing import NamedTuple

import httpx
from fastapi import Request, Response

from app.core.config import settings
from app.core.metrics import UPSTREAM_DURATION, UPSTREAM_REQUESTS

# Headers that describe a single network hop, not the request itself.
# Forwarding them would confuse the next hop (wrong Host, stale Content-Length).
HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    }
)


class UnknownRouteError(Exception):
    """No downstream service owns this resource."""


class UpstreamUnavailableError(Exception):
    """The downstream service could not be reached."""


class UpstreamTimeoutError(Exception):
    """The downstream service did not answer in time."""


class Upstream(NamedTuple):
    service: str
    base_url: str


def resolve_upstream(resource: str) -> Upstream:
    routes = {
        "orders": Upstream("order-service", settings.order_service_url),
        "products": Upstream("inventory-service", settings.inventory_service_url),
        "reservations": Upstream("inventory-service", settings.inventory_service_url),
        "charges": Upstream("payment-service", settings.payment_service_url),
        "payments": Upstream("payment-service", settings.payment_service_url),
        "recommendations": Upstream(
            "recommendation-service", settings.recommendation_service_url
        ),
    }
    try:
        return routes[resource]
    except KeyError as exc:
        raise UnknownRouteError(resource) from exc


async def forward(
    client: httpx.AsyncClient,
    request: Request,
    path: str,
) -> Response:
    resource = path.split("/", 1)[0]
    upstream_service = resolve_upstream(resource)

    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }
    body = await request.body()

    started = time.perf_counter()
    try:
        upstream = await client.request(
            request.method,
            f"{upstream_service.base_url.rstrip('/')}/{path}",
            params=list(request.query_params.multi_items()),
            headers=headers,
            content=body,
        )
    except httpx.TimeoutException as exc:
        _record_upstream(upstream_service.service, "timeout", started)
        raise UpstreamTimeoutError(resource) from exc
    except httpx.RequestError as exc:
        _record_upstream(upstream_service.service, "unavailable", started)
        raise UpstreamUnavailableError(resource) from exc
    _record_upstream(upstream_service.service, str(upstream.status_code), started)

    # httpx already decompressed the body, so the original encoding header would lie.
    excluded = HOP_BY_HOP_HEADERS | {"content-encoding"}
    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() not in excluded
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )


def _record_upstream(service: str, outcome: str, started: float) -> None:
    UPSTREAM_REQUESTS.labels(service, outcome).inc()
    UPSTREAM_DURATION.labels(service).observe(time.perf_counter() - started)
