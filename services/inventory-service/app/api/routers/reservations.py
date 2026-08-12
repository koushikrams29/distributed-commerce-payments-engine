import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from commerce_common.auth import AccessTokenPayload

from app.core.db import get_db
from app.core.security import get_current_user
from app.schemas.inventory import ReserveRequest, ReserveResponse
from app.services.inventory_service import (
    InsufficientStockError,
    InventoryService,
    ProductNotFoundError,
)

router = APIRouter(prefix="/reservations", tags=["reservations"])


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

    return ReserveResponse(order_id=payload.order_id, reservations=reservations)


@router.post("/{order_id}/release", status_code=status.HTTP_200_OK)
def release_stock(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user: AccessTokenPayload = Depends(get_current_user),
):
    released = InventoryService(db).release_for_order(order_id)
    return {"order_id": str(order_id), "released_count": released}
