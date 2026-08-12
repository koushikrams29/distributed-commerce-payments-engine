import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from commerce_common.auth import AccessTokenPayload, Role

from app.core.db import get_db
from app.core.security import require_roles
from app.schemas.inventory import ProductDetail, ProductListResponse, ProductRead
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
    _admin: AccessTokenPayload = Depends(require_roles(Role.ADMIN)),
):
    service = InventoryService(db)
    product = service.get_product(product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )
    return ProductDetail(
        id=product.id,
        name=product.name,
        price=product.price,
        stock_qty=product.stock_qty,
        active_reservations=service.list_active_reservations(product_id),
    )
