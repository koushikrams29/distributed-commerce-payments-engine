import httpx
from fastapi import Request


def get_http_client(request: Request) -> httpx.AsyncClient:
    """One pooled client per process, created in the app lifespan."""
    return request.app.state.http_client
