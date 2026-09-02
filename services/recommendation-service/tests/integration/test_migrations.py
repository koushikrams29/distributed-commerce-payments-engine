from alembic import command
from alembic.config import Config
from pathlib import Path


def test_migrations_apply_cleanly(database_url: str) -> None:
    service_root = Path(__file__).resolve().parents[2]
    config = Config(str(service_root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
