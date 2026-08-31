from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    jwt_secret: str
    # Mock gateway outcome for local dev: success | failure
    mock_payment_outcome: str = "success"


settings = Settings()
