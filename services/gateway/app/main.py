from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from commerce_common.auth import Role
from commerce_common.observability import setup_observability

from app.api.routers import auth, dashboard, proxy
from app.core.config import settings
from app.core.db import SessionLocal, engine, get_db
from app.realtime.events import start_dashboard_event_relay
from app.realtime.hub import DashboardHub
from app.services.auth_service import AuthService
from app.services.rate_limiter import TokenBucketLimiter


def _seed_dev_users() -> None:
    if not settings.seed_dev_users:
        return
    db = SessionLocal()
    try:
        service = AuthService(db)
        service.ensure_user(
            email="shopper@example.com",
            password=settings.seed_shopper_password,
            role=Role.SHOPPER,
        )
        service.ensure_user(
            email="admin@example.com",
            password=settings.seed_admin_password,
            role=Role.ADMIN,
        )
    finally:
        db.close()


def _build_limiters(redis: Redis | None) -> tuple[TokenBucketLimiter | None, ...]:
    if redis is None:
        return None, None
    api = TokenBucketLimiter(
        redis,
        name="api",
        capacity=settings.rate_limit_api_capacity,
        refill_per_second=settings.rate_limit_api_refill_per_second,
    )
    auth_limiter = TokenBucketLimiter(
        redis,
        name="auth",
        capacity=settings.rate_limit_auth_capacity,
        refill_per_second=settings.rate_limit_auth_refill_per_second,
    )
    return api, auth_limiter


@asynccontextmanager
async def lifespan(app: FastAPI):
    _seed_dev_users()
    redis = (
        Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        if settings.rate_limit_enabled
        else None
    )
    app.state.api_limiter, app.state.auth_limiter = _build_limiters(redis)
    app.state.dashboard_hub = DashboardHub()
    if settings.dashboard_events_enabled:
        start_dashboard_event_relay(app.state.dashboard_hub)
    try:
        async with httpx.AsyncClient(timeout=settings.proxy_timeout_seconds) as client:
            app.state.http_client = client
            yield
    finally:
        if redis is not None:
            await redis.aclose()


app = FastAPI(title="Gateway Service", version="0.1.0", lifespan=lifespan)
setup_observability(
    app,
    service_name="gateway",
    settings=settings,
    engine=engine,
    # A dashboard socket stays open for hours; one span that long is useless.
    untraced_paths=("ws/dashboard",),
)
if settings.cors_allowed_origins:
    # Only needed when the dashboard is served from another origin (e.g. a
    # CDN); in local dev the Vite proxy makes it same-origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "Retry-After"],
    )
app.include_router(dashboard.router)
# Unversioned /auth kept so existing clients and scripts keep working.
app.include_router(auth.router, include_in_schema=False)
app.include_router(auth.router, prefix="/api/v1")
# Must come after the /api/v1 auth routes: its catch-all path would shadow them.
app.include_router(proxy.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/health/db")
def db_health_check(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
