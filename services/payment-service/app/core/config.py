from typing import Literal

from pydantic_settings import SettingsConfigDict

from commerce_common.observability import ObservabilitySettings


class Settings(ObservabilitySettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    jwt_secret: str
    # Mock gateway outcome for local dev; any other value fails at startup.
    mock_payment_outcome: Literal["success", "failure"] = "success"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    use_event_bus: bool = True


settings = Settings()
