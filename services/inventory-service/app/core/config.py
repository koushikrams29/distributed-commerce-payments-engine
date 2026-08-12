from datetime import timedelta

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    jwt_secret: str
    seed_dev_products: bool = False
    # How long a held reservation stays valid before a reconciler can release it.
    reservation_ttl_minutes: int = 15


settings = Settings()
