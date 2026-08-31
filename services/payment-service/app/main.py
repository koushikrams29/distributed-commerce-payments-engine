from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routers import charges, payments
from app.core.db import get_db

app = FastAPI(title="Payment Service", version="0.1.0")
app.include_router(charges.router)
app.include_router(payments.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/health/db")
def db_health_check(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
