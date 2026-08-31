import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from commerce_common.auth import AccessTokenPayload, Role

from app.core.db import get_db
from app.core.security import require_roles
from app.schemas.payment import PaymentRead
from app.services.payment_service import PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("/{order_id}", response_model=PaymentRead)
def get_payment_for_order(
    order_id: uuid.UUID,
    db: Session = Depends(get_db),
    _admin: AccessTokenPayload = Depends(require_roles(Role.ADMIN)),
):
    payment = PaymentService(db).get_payment_for_order(order_id)
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="payment not found"
        )
    return PaymentRead.from_payment(payment)
