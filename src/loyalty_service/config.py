from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'postgresql+psycopg://loyalty:loyalty@localhost:5435/loyalty'
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: Literal['HS256'] = 'HS256'
    internal_api_token: str = Field(min_length=16)
    payment_mode: Literal['mock'] = 'mock'
    enable_mock_payment_control: bool = False
    reservation_minutes: int = Field(default=15, ge=1, le=60)
