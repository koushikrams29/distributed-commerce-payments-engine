from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routers import orders
from app.core.config import settings
from app.core.db import get_db
from app.events.consumers import start_order_event_consumers
from app.events.outbox_relay import start_outbox_relay
from app.events.reconciler import start_order_reconciler


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.use_event_bus:
        start_outbox_relay()
        start_order_event_consumers()
    if settings.reconcile_enabled:
        start_order_reconciler()
    yield


app = FastAPI(title="Order Service", version="0.1.0", lifespan=lifespan)

app.include_router(orders.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/health/db")
def db_health_check(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
