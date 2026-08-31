from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from commerce_common.auth import AccessTokenPayload

from app.core.db import get_db
from app.core.security import get_current_user
from app.schemas.payment import ChargeRequest, PaymentRead
from app.services.payment_service import PaymentService

router = APIRouter(prefix="/charges", tags=["charges"])


@router.post("", response_model=PaymentRead)
def charge_order(
    payload: ChargeRequest,
    response: Response,
    db: Session = Depends(get_db),
    # Until RabbitMQ lands, Order Service calls this over HTTP.
    _user: AccessTokenPayload = Depends(get_current_user),
):
    payment, created = PaymentService(db).charge(
        order_id=payload.order_id,
        amount=payload.amount,
        idempotency_key=payload.idempotency_key,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    else:
        response.status_code = status.HTTP_201_CREATED
    return PaymentRead.from_payment(payment)
