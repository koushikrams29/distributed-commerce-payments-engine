"""Guards against a model being edited without a matching migration."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine

from app.core.db import Base
from app.models import RefreshToken, User  # noqa: F401


def test_migrations_produce_the_schema_the_models_expect(engine: Engine) -> None:
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        differences = compare_metadata(context, Base.metadata)

    assert differences == [], f"Models and migrations disagree: {differences}"
