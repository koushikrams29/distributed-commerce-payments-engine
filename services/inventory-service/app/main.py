from contextlib import asynccontextmanager
from decimal import Decimal

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routers import products, reservations
from app.core.config import settings
from app.core.db import SessionLocal, get_db
from app.services.inventory_service import InventoryService

# Fixed IDs so local demos and Order Service tests can target known products.
DEV_PRODUCTS = (
    {
        "id": "22222222-2222-2222-2222-222222222222",
        "name": "Demo Widget",
        "price": Decimal("100.00"),
        "stock_qty": 10,
    },
    {
        "id": "33333333-3333-3333-3333-333333333333",
        "name": "Demo Gadget",
        "price": Decimal("50.00"),
        "stock_qty": 5,
    },
)


def _seed_dev_products() -> None:
    if not settings.seed_dev_products:
        return
    import uuid

    from app.models import Product

    db = SessionLocal()
    try:
        service = InventoryService(db)
        for item in DEV_PRODUCTS:
            existing = service.products.get_by_name(item["name"])
            if existing is not None:
                continue
            product = Product(
                id=uuid.UUID(item["id"]),
                name=item["name"],
                price=item["price"],
                stock_qty=item["stock_qty"],
            )
            service.products.add(product)
            db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _seed_dev_products()
    yield


app = FastAPI(title="Inventory Service", version="0.1.0", lifespan=lifespan)
app.include_router(products.router)
app.include_router(reservations.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/health/db")
def db_health_check(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
