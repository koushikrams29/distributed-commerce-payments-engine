import uuid
from decimal import Decimal
from typing import Any

from commerce_common.auth import Role, create_access_token
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models import Product


def auth_header(*, role: Role = Role.ADMIN) -> dict[str, str]:
    token = create_access_token(
        secret=settings.jwt_secret,
        user_id=uuid.uuid4(),
        role=role,
        expires_minutes=15,
    )
    return {"Authorization": f"Bearer {token}"}


def seed_product(
    session_factory: sessionmaker[Session],
    *,
    stock_qty: int = 1,
    name: str | None = None,
    product_id: uuid.UUID | None = None,
) -> Product:
    db = session_factory()
    try:
        product = Product(
            id=product_id or uuid.uuid4(),
            name=name or f"Product {uuid.uuid4().hex[:8]}",
            price=Decimal("100.00"),
            stock_qty=stock_qty,
        )
        db.add(product)
        db.commit()
        db.refresh(product)
        db.expunge(product)
        return product
    finally:
        db.close()


def reserve_payload(
    *,
    product_id: uuid.UUID,
    qty: int = 1,
    order_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    return {
        "order_id": str(order_id or uuid.uuid4()),
        "items": [{"product_id": str(product_id), "qty": qty}],
    }
