from typing import Literal

from pydantic_settings import SettingsConfigDict

from commerce_common.observability import ObservabilitySettings


class Settings(ObservabilitySettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    jwt_secret: str
    # Deterministic local gateway scenarios. A timeout has an ambiguous result;
    # reconciliation uses MOCK_PAYMENT_TIMEOUT_RESOLUTION instead of charging again.
    mock_payment_outcome: Literal["success", "failure", "timeout"] = "success"
    mock_payment_timeout_resolution: Literal["success", "failure", "unknown"] = (
        "unknown"
    )
    mock_payment_latency_seconds: float = 0.0
    payment_reconcile_enabled: bool = True
    payment_reconcile_after_seconds: int = 30
    payment_reconcile_poll_interval_seconds: int = 10
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    use_event_bus: bool = True


settings = Settings()
