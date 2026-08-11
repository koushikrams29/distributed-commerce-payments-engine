import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from commerce_common.auth import AccessTokenPayload, Role

from app.core.db import get_db
from app.core.security import get_current_user
from app.schemas.order import OrderCreate, OrderRead
from app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreate,
    response: Response,
    db: Session = Depends(get_db),
    user: AccessTokenPayload = Depends(get_current_user),
):
    order, created = OrderService(db).create_order(payload, user_id=user.user_id)
    if not created:
        response.status_code = status.HTTP_200_OK
    return order


@router.get("/{order_id}", response_model=OrderRead)
def get_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: AccessTokenPayload = Depends(get_current_user),
):
    order = OrderService(db).get_order(order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )

    # Shoppers may only read their own orders. Admins may read any.
    # Use 404 (not 403) for cross-user reads so we don't leak that the id exists.
    if user.role != Role.ADMIN and order.user_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )

    return order
