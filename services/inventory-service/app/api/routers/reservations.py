import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from commerce_common.auth import AccessTokenPayload, Role

from app.core.db import get_db
from app.core.security import get_current_user, require_roles
from app.models import ReservationStatus
from app.schemas.inventory import (
    ReservationListResponse,
    ReserveRequest,
    ReserveResponse,
)
from app.services.inventory_service import (
    InsufficientStockError,
    InventoryService,
    ProductNotFoundError,
    ReservationConflictError,
)

router = APIRouter(prefix="/reservations", tags=["reservations"])

_VALID_STATUSES = {s.value for s in ReservationStatus}


@router.get("", response_model=ReservationListResponse)
def list_reservations(
    db: Session = Depends(get_db),
    _admin: AccessTokenPayload = Depends(require_roles(Role.ADMIN)),
    order_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Admin-only: recent reservation rows, newest first."""
    if status_filter is not None and status_filter not in _VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status must be one of: {sorted(_VALID_STATUSES)}",
        )
    return ReservationListResponse(
        items=InventoryService(db).list_reservations(
            limit=limit, order_id=order_id, status=status_filter
        )
    )


@router.post("", response_model=ReserveResponse, status_code=status.HTTP_201_CREATED)
def reserve_stock(
    payload: ReserveRequest,
    db: Session = Depends(get_db),
    # Until RabbitMQ lands, Order Service (or tests) call this over HTTP.
    # Any authenticated principal may reserve; Gateway will gate public access.
    _user: AccessTokenPayload = Depends(get_current_user),
):
    try:
        reservations = InventoryService(db).reserve(
            order_id=payload.order_id, items=payload.items
        )
    except ProductNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"product not found: {exc.product_id}",
        ) from exc
    except InsufficientStockError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "insufficient stock",
                "product_id": str(exc.product_id),
                "requested": exc.requested,
                "available": exc.available,
            },
        ) from exc
    except ReservationConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="order_id already has a reservation with a different payload",
        ) from exc

    return ReserveResponse(order_id=payload.order_id, reservations=reservations)


@router.post("/{order_id}/release", status_code=status.HTTP_200_OK)
def release_stock(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: AccessTokenPayload = Depends(get_current_user),
):
    released = InventoryService(db).release_for_order(order_id)
    return {"order_id": str(order_id), "released_count": released}


@router.post("/{order_id}/commit", status_code=status.HTTP_200_OK)
def commit_stock(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: AccessTokenPayload = Depends(get_current_user),
):
    committed = InventoryService(db).commit_for_order(order_id)
    return {"order_id": str(order_id), "committed_count": committed}
