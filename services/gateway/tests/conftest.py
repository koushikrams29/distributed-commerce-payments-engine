"""Shared fixtures for the Gateway test suite.

Environment variables are set BEFORE importing the app so Settings picks up
test-safe values instead of the developer's local .env.
"""

import os
from pathlib import Path
from typing import Iterator

# Must run before any `app.*` import — Settings reads the environment at import.
os.environ["DATABASE_URL"] = (
    "postgresql+psycopg2://ci:ci@localhost:5432/ci_unused_placeholder"
)
os.environ["JWT_SECRET"] = "test-secret-at-least-32-characters-long"
os.environ["SEED_DEV_USERS"] = "false"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "15"
os.environ["REFRESH_TOKEN_EXPIRE_DAYS"] = "7"

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import get_db
from app.main import app

SERVICE_ROOT = Path(__file__).resolve().parents[1]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
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
        connection.execute(text("TRUNCATE refresh_tokens, users CASCADE"))


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    def override_get_db() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
