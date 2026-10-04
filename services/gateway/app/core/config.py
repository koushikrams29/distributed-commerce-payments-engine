from pydantic_settings import SettingsConfigDict

from commerce_common.observability import ObservabilitySettings


class Settings(ObservabilitySettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    jwt_secret: str
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    seed_dev_users: bool = False
    # Applied only when the account is first created; changing them later has no effect.
    seed_admin_password: str = "admin-pass-123"
    seed_shopper_password: str = "shopper-pass-123"

    order_service_url: str = "http://127.0.0.1:8000"
    inventory_service_url: str = "http://127.0.0.1:8002"
    payment_service_url: str = "http://127.0.0.1:8003"
    recommendation_service_url: str = "http://127.0.0.1:8005"
    proxy_timeout_seconds: float = 10.0

    redis_url: str = "redis://localhost:6379/0"
    rate_limit_enabled: bool = True
    # Per user: bursts of 20, sustained 5 requests/second.
    rate_limit_api_capacity: int = 20
    rate_limit_api_refill_per_second: float = 5.0
    # Per client IP on login/refresh: 5 attempts, then one every 12 seconds.
    rate_limit_auth_capacity: int = 5
    rate_limit_auth_refill_per_second: float = 1 / 12

    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    dashboard_events_enabled: bool = True
    dashboard_auth_timeout_seconds: float = 5.0
    # JSON list, e.g. ["https://dashboard.example.com"]. Empty = same-origin only.
    cors_allowed_origins: list[str] = []


settings = Settings()
