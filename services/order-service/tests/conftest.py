"""Shared fixtures for the Order Service test suite.

JWT_SECRET is set before importing the app so Settings validates even when a
developer runs tests without a local .env.
"""

import os
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Iterator

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg2://ci:ci@localhost:5432/ci_unused_placeholder",
)
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("INVENTORY_SERVICE_URL", "http://inventory.test")

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.routers.orders import get_inventory_client
from app.clients.inventory import ProductInfo
from app.core.db import get_db
from app.main import app

SERVICE_ROOT = Path(__file__).resolve().parents[1]


class FakeInventoryClient:
    """Stand-in for Inventory so order tests do not need a second container."""

    def __init__(self, *, price: Decimal = Decimal("100.00"), reserve_ok: bool = True):
        self.price = price
        self.reserve_ok = reserve_ok
        self.reserve_calls: list[uuid.UUID] = []

    def get_product(self, product_id: uuid.UUID, *, access_token: str) -> ProductInfo:
        return ProductInfo(
            id=product_id,
            name="Test Product",
            price=self.price,
            stock_qty=100,
        )

    def reserve(
        self, *, order_id: uuid.UUID, items: list[dict], access_token: str
    ) -> None:
        from app.clients.inventory import InsufficientStockError

        self.reserve_calls.append(order_id)
        if not self.reserve_ok:
            raise InsufficientStockError({"message": "insufficient stock"})


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark everything under tests/integration/ so it can be skipped with -m."""
    for item in items:
        if "integration" in Path(str(item.fspath)).parts:
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer("postgres:16", driver="psycopg2") as container:
        url = container.get_connection_url()
        _upgrade_to_head(url)
        yield url


def _upgrade_to_head(url: str) -> None:
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url, pool_pre_ping=True)
    # BackgroundTasks open SessionLocal() directly — bind it to the same
    # throwaway database the request path uses via get_db override.
    from app.core.db import SessionLocal

    SessionLocal.configure(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def clean_tables(request: pytest.FixtureRequest) -> None:
    if "engine" not in request.fixturenames:
        return
    engine = request.getfixturevalue("engine")
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE orders CASCADE"))


@pytest.fixture
def fake_inventory() -> FakeInventoryClient:
    return FakeInventoryClient()


@pytest.fixture
def client(
    session_factory: sessionmaker[Session], fake_inventory: FakeInventoryClient
) -> Iterator[TestClient]:
    def override_get_db() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_inventory_client] = lambda: fake_inventory
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
