import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from commerce_common.auth import AccessTokenPayload, Role

from app.core.db import get_db
from app.core.security import get_current_user, require_roles
from app.schemas.inventory import ProductDetail, ProductListResponse
from app.services.inventory_service import InventoryService

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=ProductListResponse)
def list_products(
    db: Session = Depends(get_db),
    _admin: AccessTokenPayload = Depends(require_roles(Role.ADMIN)),
):
    products = InventoryService(db).list_products()
    return ProductListResponse(items=products)


@router.get("/{product_id}", response_model=ProductDetail)
def get_product(
    product_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: AccessTokenPayload = Depends(get_current_user),
):
    """Any authenticated user may read catalogue fields (needed at checkout).

    Active reservation details stay admin-only so shoppers cannot inspect
    other customers' holds.
    """
    service = InventoryService(db)
    product = service.get_product(product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )

    active = []
    if user.role == Role.ADMIN:
        active = service.list_active_reservations(product_id)

    return ProductDetail(
        id=product.id,
        name=product.name,
        price=product.price,
        stock_qty=product.stock_qty,
        active_reservations=active,
    )
