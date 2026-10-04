import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from commerce_common.auth import AccessTokenPayload, Role
from commerce_common.pagination import CursorError

from app.core.db import get_db
from app.core.security import require_roles
from app.models import PaymentStatus
from app.schemas.payment import PaymentListResponse, PaymentRead, PaymentSummary
from app.services.payment_service import PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])

_VALID_STATUSES = {s.value for s in PaymentStatus}


@router.get("", response_model=PaymentListResponse)
def list_payments(
    db: Session = Depends(get_db),
    _admin: AccessTokenPayload = Depends(require_roles(Role.ADMIN)),
    status_filter: str | None = Query(default=None, alias="status"),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Admin-only cursor-paginated list of charges (newest first)."""
    if status_filter is not None and status_filter not in _VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status must be one of: {sorted(_VALID_STATUSES)}",
        )
    try:
        return PaymentService(db).list_payments(
            limit=limit, status=status_filter, cursor=cursor
        )
    except CursorError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid cursor"
        ) from exc


# Declared before /{order_id}, which would otherwise try to parse "summary" as a UUID.
@router.get("/summary", response_model=PaymentSummary)
def payment_summary(
    db: Session = Depends(get_db),
    _admin: AccessTokenPayload = Depends(require_roles(Role.ADMIN)),
):
    """Admin-only: charges by status and money moved, from the ledger."""
    return PaymentService(db).summary()


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
