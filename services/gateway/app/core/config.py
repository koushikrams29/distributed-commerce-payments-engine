from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    jwt_secret: str
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    seed_dev_users: bool = False

    order_service_url: str = "http://127.0.0.1:8000"
    inventory_service_url: str = "http://127.0.0.1:8002"
    payment_service_url: str = "http://127.0.0.1:8003"
    recommendation_service_url: str = "http://127.0.0.1:8005"
    proxy_timeout_seconds: float = 10.0


settings = Settings()
