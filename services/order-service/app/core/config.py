from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    # Must match the Gateway's JWT_SECRET so tokens issued there verify here.
    jwt_secret: str
    inventory_service_url: str = "http://127.0.0.1:8002"


settings = Settings()
