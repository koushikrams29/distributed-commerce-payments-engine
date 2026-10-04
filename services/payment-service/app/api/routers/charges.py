from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from commerce_common.auth import AccessTokenPayload

from app.core.db import get_db
from app.core.security import get_current_user
from app.schemas.payment import ChargeRequest, PaymentRead
from app.services.payment_service import IdempotencyKeyReusedError, PaymentService

router = APIRouter(prefix="/charges", tags=["charges"])


@router.post(
    "",
    response_model=PaymentRead,
    responses={status.HTTP_409_CONFLICT: {"description": "Key reused for a different charge"}},
)
def charge_order(
    payload: ChargeRequest,
    response: Response,
    db: Session = Depends(get_db),
    # Order Service calls this over HTTP when the event bus is off.
    _user: AccessTokenPayload = Depends(get_current_user),
):
    try:
        payment, created = PaymentService(db).charge(
            order_id=payload.order_id,
            amount=payload.amount,
            idempotency_key=payload.idempotency_key,
        )
    except IdempotencyKeyReusedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return PaymentRead.from_payment(payment)
