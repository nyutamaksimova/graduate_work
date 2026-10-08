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
    redis_url: str = 'redis://localhost:6385/0'
    promo_user_limit: int = Field(default=10, ge=1)
    promo_ip_limit: int = Field(default=30, ge=1)
    promo_window_seconds: int = Field(default=60, ge=1)
    promo_failure_threshold: int = Field(default=5, ge=1)
    promo_failure_window_seconds: int = Field(default=300, ge=1)
    promo_block_seconds: int = Field(default=900, ge=1)
