from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Horizon(str, Enum):
    SWING = "swing"
    INTRADAY = "intraday"
    DAY_TRADING = "day_trading"


class Candidate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    symbol: str
    name: str | None = None
    price: float | None = None
    change_percent: float | None = None
    volume: float | None = None
    market_cap: float | None = None
    sector: str | None = None
    exchange: str | None = None


class OHLCVBar(BaseModel):
    time: datetime
    open: float = Field(allow_inf_nan=False)
    high: float = Field(allow_inf_nan=False)
    low: float = Field(allow_inf_nan=False)
    close: float = Field(allow_inf_nan=False)
    volume: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_ohlc(self) -> "OHLCVBar":
        if (
            self.high < self.low
            or self.high < max(self.open, self.close)
            or self.low > min(self.open, self.close)
        ):
            raise ValueError("OHLC values are inconsistent.")
        return self


class HistoricalDataMetadata(BaseModel):
    symbol: str
    bar_size: str
    duration: str
    use_rth: bool
    bar_count: int = Field(ge=0)
    start_time: datetime | None = None
    end_time: datetime | None = None


class ResearchSignal(BaseModel):
    symbol: str
    timestamp: datetime
    horizon: Horizon
    current_price: float
    indicators: dict[str, float | str | None]
    direction: Literal["bullish", "bearish", "neutral"]
    score: int = Field(ge=-100, le=100)
    explanation: str


class SymbolFailure(BaseModel):
    symbol: str
    reason: str


class ScanResponse(BaseModel):
    scan_id: int
    horizon: Horizon
    candidates: int
    signals: list[ResearchSignal]
    failed_symbols: list[SymbolFailure]


class StoredSignal(ResearchSignal):
    scan_id: int
    created_at: datetime
