from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from commerce_common.observability import setup_observability

from app.api.routers import charges, payments
from app.core.config import settings
from app.core.db import engine, get_db
from app.events.consumers import start_payment_event_consumers
from app.events.reconciler import start_payment_reconciler


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.use_event_bus:
        start_payment_event_consumers()
        if settings.payment_reconcile_enabled:
            start_payment_reconciler()
    yield


app = FastAPI(title="Payment Service", version="0.1.0", lifespan=lifespan)
setup_observability(app, service_name="payment-service", settings=settings, engine=engine)
app.include_router(charges.router)
app.include_router(payments.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/health/db")
def db_health_check(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
