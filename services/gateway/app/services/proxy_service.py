import httpx
from fastapi import Request, Response

from app.core.config import settings

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


def resolve_upstream(resource: str) -> str:
    routes = {
        "orders": settings.order_service_url,
        "products": settings.inventory_service_url,
        "reservations": settings.inventory_service_url,
        "charges": settings.payment_service_url,
        "payments": settings.payment_service_url,
        "recommendations": settings.recommendation_service_url,
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
    base_url = resolve_upstream(resource)

    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }

    try:
        upstream = await client.request(
            request.method,
            f"{base_url.rstrip('/')}/{path}",
            params=list(request.query_params.multi_items()),
            headers=headers,
            content=await request.body(),
        )
    except httpx.TimeoutException as exc:
        raise UpstreamTimeoutError(resource) from exc
    except httpx.RequestError as exc:
        raise UpstreamUnavailableError(resource) from exc

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
