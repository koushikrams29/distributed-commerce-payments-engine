import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from commerce_common.auth import AccessTokenPayload, Role

from app.core.cursors import CursorError
from app.core.db import get_db
from app.core.security import get_current_user, require_roles
from app.models import OrderStatus
from app.schemas.order import OrderCreate, OrderListResponse, OrderRead
from app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])

_VALID_STATUSES = {s.value for s in OrderStatus}


@router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreate,
    response: Response,
    db: Session = Depends(get_db),
    user: AccessTokenPayload = Depends(
        require_roles(Role.SHOPPER, Role.ADMIN)
    ),
):
    """Shoppers place orders; admins may also create (support / demos)."""
    order, created = OrderService(db).create_order(payload, user_id=user.user_id)
    if not created:
        response.status_code = status.HTTP_200_OK
    return order


@router.get("", response_model=OrderListResponse)
def list_orders(
    db: Session = Depends(get_db),
    _admin: AccessTokenPayload = Depends(require_roles(Role.ADMIN)),
    status_filter: str | None = Query(default=None, alias="status"),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Admin-only cursor-paginated list (newest first)."""
    if status_filter is not None and status_filter not in _VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status must be one of: {sorted(_VALID_STATUSES)}",
        )
    try:
        return OrderService(db).list_orders(
            limit=limit, status=status_filter, cursor=cursor
        )
    except CursorError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid cursor",
        ) from exc


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
