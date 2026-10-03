from pydantic_settings import SettingsConfigDict

from commerce_common.observability import ObservabilitySettings


class Settings(ObservabilitySettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    use_event_bus: bool = True
    default_channel: str = "email"


settings = Settings()
