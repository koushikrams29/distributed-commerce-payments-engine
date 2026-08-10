from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from commerce_common.auth import Role

from app.api.routers import auth
from app.core.config import settings
from app.core.db import SessionLocal, get_db
from app.services.auth_service import AuthService


def _seed_dev_users() -> None:
    if not settings.seed_dev_users:
        return
    db = SessionLocal()
    try:
        service = AuthService(db)
        service.ensure_user(
            email="shopper@example.com",
            password="shopper-pass-123",
            role=Role.SHOPPER,
        )
        service.ensure_user(
            email="admin@example.com",
            password="admin-pass-123",
            role=Role.ADMIN,
        )
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _seed_dev_users()
    yield


app = FastAPI(title="Gateway Service", version="0.1.0", lifespan=lifespan)
app.include_router(auth.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/health/db")
def db_health_check(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
