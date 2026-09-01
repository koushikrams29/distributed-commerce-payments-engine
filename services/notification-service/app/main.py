from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.events.consumers import start_notification_event_consumers


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.use_event_bus:
        start_notification_event_consumers()
    yield


app = FastAPI(title="Notification Service", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/health/db")
def db_health_check(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
