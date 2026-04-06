from pydantic_settings import BaseSettings
from pydantic import Field, SecretStr


class Settings(BaseSettings):
    # Pydantic looks for environment variables named 'API_KEY' and 'DEBUG'
    ws_email: str = Field(...)
    ws_password: str = Field(...)
    ws_totp_secret: SecretStr = Field(...)
    LOG_LEVEL: str = Field(default="INFO")


settings = Settings
