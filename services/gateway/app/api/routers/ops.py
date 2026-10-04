import logging

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status

from commerce_common.auth import AccessTokenPayload, Role
from commerce_common.messaging.replay import UnknownQueueError

from app.api.rate_limit import get_api_limiter, raise_if_limited
from app.api.routers.proxy import require_access_token
from app.core.http import get_http_client
from app.schemas.ops import (
    DeadLetterPage,
    QueueOverview,
    ReplayRequest,
    ReplayResult,
    SystemHealth,
)
from app.services import ops_service
from app.services.rate_limiter import TokenBucketLimiter

logger = logging.getLogger(__name__)


async def require_admin(
    caller: AccessTokenPayload = Depends(require_access_token),
    limiter: TokenBucketLimiter | None = Depends(get_api_limiter),
) -> AccessTokenPayload:
    """Ops views are the gateway's own resources, so it enforces the role itself."""
    if caller.role != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient permissions")
    if limiter is not None:
        raise_if_limited(await limiter.consume(str(caller.user_id)))
    return caller


router = APIRouter(prefix="/api/v1/ops", tags=["ops"], dependencies=[Depends(require_admin)])


def _queue_or_404(queue: str) -> str:
    if not ops_service.valid_queue_name(queue):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown queue")
    return queue


@router.get("/health", response_model=SystemHealth)
async def system_health(
    request: Request, client: httpx.AsyncClient = Depends(get_http_client)
):
    """Every service and piece of infrastructure the order flow depends on."""
    return await ops_service.system_health(client, redis=request.app.state.redis)


@router.get("/queues", response_model=QueueOverview)
async def queues(client: httpx.AsyncClient = Depends(get_http_client)):
    """Each service's work queue with its backlog, retries and dead letters."""
    try:
        return await ops_service.queue_overview(client)
    except ops_service.BrokerUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("/dead-letters/{queue}", response_model=DeadLetterPage)
async def dead_letters(queue: str, limit: int = Query(default=20, ge=1, le=100)):
    """The oldest dead letters of a work queue. Reading does not remove them."""
    try:
        return await ops_service.dead_letters(_queue_or_404(queue), limit=limit)
    except UnknownQueueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown queue") from exc


@router.post("/dead-letters/{queue}/replay", response_model=ReplayResult)
async def replay_dead_letters(
    queue: str,
    payload: ReplayRequest = Body(default_factory=ReplayRequest),
    caller: AccessTokenPayload = Depends(require_admin),
):
    """Return dead letters to their work queue with a fresh set of retries."""
    try:
        replayed = await ops_service.replay(_queue_or_404(queue), limit=payload.limit)
    except UnknownQueueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown queue") from exc
    logger.warning(
        "admin %s replayed %d dead letter(s) on %s", caller.user_id, replayed, queue
    )
    return ReplayResult(queue=queue, replayed=replayed)
