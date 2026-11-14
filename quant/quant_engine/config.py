from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    openterminal_api_url: str = "http://127.0.0.1:4000"
    openterminal_timeout_seconds: float = Field(default=10.0, gt=0, le=60)

    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = Field(default=7497, ge=1, le=65535)
    ibkr_client_id: int = Field(default=31, ge=0)
    ibkr_timeout_seconds: float = Field(default=8.0, gt=0, le=60)

    database_path: str = "./data/quant.db"

    swing_duration: str = "2 Y"
    swing_bar_size: str = "1 day"
    intraday_duration: str = "5 D"
    intraday_bar_size: str = "5 mins"
    day_trading_duration: str = "1 D"
    day_trading_bar_size: str = "5 mins"

    @field_validator("openterminal_api_url")
    @classmethod
    def trim_api_url(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("ibkr_port")
    @classmethod
    def paper_trading_port_only(cls, value: int) -> int:
        if value not in {7497, 4002}:
            raise ValueError("IBKR_PORT must be a paper-trading port: 7497 or 4002.")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
