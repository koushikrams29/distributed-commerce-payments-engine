import uuid
from datetime import datetime

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from commerce_common.auth import AccessTokenPayload, Role

from app.clients.inventory import (
    InventoryClient,
    InventoryUnavailableError,
    ProductNotFoundError,
)
from app.clients.payment import PaymentClient
from app.core.config import settings
from app.core.cursors import CursorError
from app.core.db import get_db
from app.core.security import bearer_scheme, get_current_user, require_roles
from app.models import OrderStatus
from app.schemas.order import (
    OrderCreate,
    OrderEventRead,
    OrderListResponse,
    OrderRead,
    OrderSummary,
)
from app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])

_VALID_STATUSES = {s.value for s in OrderStatus}


def get_inventory_client() -> InventoryClient:
    return InventoryClient()


def get_payment_client() -> PaymentClient:
    return PaymentClient()


@router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreate,
    response: Response,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: AccessTokenPayload = Depends(
        require_roles(Role.SHOPPER, Role.ADMIN)
    ),
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    inventory: InventoryClient = Depends(get_inventory_client),
    payment: PaymentClient = Depends(get_payment_client),
):
    """Create pending order, then reserve stock in the background (FR-1)."""
    service = OrderService(db, inventory=inventory, payment=payment)
    try:
        order, created = service.create_order(
            payload,
            user_id=user.user_id,
            access_token=credentials.credentials,
        )
    except ProductNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"product not found: {exc.product_id}",
        ) from exc
    except InventoryUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="inventory service unavailable",
        ) from exc

    if not created:
        response.status_code = status.HTTP_200_OK
    elif not settings.use_event_bus:
        background_tasks.add_task(
            service.reserve_inventory,
            order.id,
            access_token=credentials.credentials,
        )
    return order


@router.get("", response_model=OrderListResponse)
def list_orders(
    db: Session = Depends(get_db),
    _admin: AccessTokenPayload = Depends(require_roles(Role.ADMIN)),
    status_filter: str | None = Query(default=None, alias="status"),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    created_from: datetime | None = Query(
        default=None, description="Only orders created at or after this instant."
    ),
    created_to: datetime | None = Query(
        default=None, description="Only orders created before this instant."
    ),
):
    """Admin-only cursor-paginated list (newest first)."""
    if status_filter is not None and status_filter not in _VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status must be one of: {sorted(_VALID_STATUSES)}",
        )
    for name, value in (("created_from", created_from), ("created_to", created_to)):
        if value is not None and value.tzinfo is None:
            # A naive time would be compared as if it were UTC, silently
            # shifting the window by the caller's UTC offset.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{name} must include a timezone offset",
            )
    try:
        return OrderService(db).list_orders(
            limit=limit,
            status=status_filter,
            cursor=cursor,
            created_from=created_from,
            created_to=created_to,
        )
    except CursorError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid cursor",
        ) from exc


# Declared before /{order_id}, which would otherwise try to parse "summary" as a UUID.
@router.get("/summary", response_model=OrderSummary)
def order_summary(
    db: Session = Depends(get_db),
    _admin: AccessTokenPayload = Depends(require_roles(Role.ADMIN)),
):
    """Admin-only health of the order pipeline: status counts, outbox backlog, overdue orders."""
    return OrderService(db).summary()


@router.get("/{order_id}/events", response_model=list[OrderEventRead])
def list_order_events(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: AccessTokenPayload = Depends(require_roles(Role.ADMIN)),
):
    """Admin-only: the events this service emitted for one order, oldest first."""
    events = OrderService(db).list_events(order_id)
    if events is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )
    return events


@router.get("/{order_id}", response_model=OrderRead)
def get_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: AccessTokenPayload = Depends(get_current_user),
):
    order = OrderService(db).get_order_for_viewer(order_id, viewer=user)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )
    return order
