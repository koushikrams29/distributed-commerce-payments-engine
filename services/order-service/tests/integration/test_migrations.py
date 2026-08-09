"""Guards against a model being edited without a matching migration."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine

from app.core.db import Base
from app.models import Order, OrderItem  # noqa: F401 - registers tables on Base


def test_migrations_produce_the_schema_the_models_expect(engine: Engine) -> None:
    """The throwaway database was built by running the real migrations.

    Comparing it against the models therefore proves the two agree. A failure
    here means a model changed without `alembic revision --autogenerate`, which
    would otherwise only surface as a runtime error after deployment.
    """
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        differences = compare_metadata(context, Base.metadata)

    assert differences == [], f"Models and migrations disagree: {differences}"
