import math
from collections.abc import Sequence

import numpy as np
import pandas as pd

from quant_engine.models import Horizon, OHLCVBar


def _value(value: object) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _ema(values: pd.Series, period: int) -> float | None:
    if len(values) < period:
        return None
    return _value(values.ewm(span=period, adjust=False, min_periods=period).mean().iloc[-1])


def _rsi(values: pd.Series, period: int = 14) -> float | None:
    changes = values.diff()
    gains = changes.clip(lower=0)
    losses = -changes.clip(upper=0)
    average_gain = gains.rolling(window=period, min_periods=period).mean().iloc[-1]
    average_loss = losses.rolling(window=period, min_periods=period).mean().iloc[-1]
    if pd.isna(average_gain) or pd.isna(average_loss):
        return None
    if average_gain == 0 and average_loss == 0:
        return 50.0
    if average_loss == 0:
        return 100.0
    if average_gain == 0:
        return 0.0
    return 100.0 - 100.0 / (1.0 + average_gain / average_loss)


def _atr(bars: Sequence[OHLCVBar], period: int = 14) -> float | None:
    if len(bars) < period + 1:
        return None
    highs = np.array([bar.high for bar in bars], dtype=float)
    lows = np.array([bar.low for bar in bars], dtype=float)
    closes = np.array([bar.close for bar in bars], dtype=float)
    previous_close = np.roll(closes, 1)
    true_range = np.maximum.reduce(
        (highs - lows, np.abs(highs - previous_close), np.abs(lows - previous_close))
    )
    true_range[0] = highs[0] - lows[0]
    return _value(pd.Series(true_range).rolling(period, min_periods=period).mean().iloc[-1])


def _momentum(values: pd.Series, periods: int) -> float | None:
    if len(values) <= periods or values.iloc[-periods - 1] == 0:
        return None
    return _value((values.iloc[-1] / values.iloc[-periods - 1] - 1.0) * 100.0)


def vwap_by_session(bars: Sequence[OHLCVBar]) -> list[float | None]:
    totals: dict[object, tuple[float, float]] = {}
    results: list[float | None] = []
    for bar in bars:
        session = bar.time.date()
        price_volume, volume = totals.get(session, (0.0, 0.0))
        typical_price = (bar.high + bar.low + bar.close) / 3.0
        price_volume += typical_price * bar.volume
        volume += bar.volume
        totals[session] = (price_volume, volume)
        results.append(price_volume / volume if volume > 0 else None)
    return results


def _relative_volume(bars: Sequence[OHLCVBar], window: int = 20) -> float | None:
    if len(bars) < 6:
        return None
    prior = [bar.volume for bar in bars[-window - 1 : -1]]
    average = float(np.mean(prior)) if prior else 0.0
    if average <= 0:
        return None
    return _value(bars[-1].volume / average)


def _trend(fast: float | None, slow: float | None) -> str:
    if fast is None or slow is None:
        return "insufficient_data"
    if fast > slow:
        return "up"
    if fast < slow:
        return "down"
    return "sideways"


def calculate_indicators(
    bars: Sequence[OHLCVBar], horizon: Horizon
) -> dict[str, float | str | None]:
    if not bars:
        raise ValueError("At least one bar is required.")
    closes = pd.Series([bar.close for bar in bars], dtype=float)
    latest = bars[-1].close

    if horizon is Horizon.SWING:
        ema20 = _ema(closes, 20)
        ema50 = _ema(closes, 50)
        atr14 = _atr(bars)
        return {
            "ema_20": ema20,
            "ema_50": ema50,
            "rsi_14": _rsi(closes),
            "atr_14": atr14,
            "momentum_10_pct": _momentum(closes, 10),
            "trend": _trend(ema20, ema50),
        }

    ema9 = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    atr14 = _atr(bars)
    vwap = vwap_by_session(bars)[-1]
    result: dict[str, float | str | None] = {
        "session_vwap": vwap,
        "momentum_3_pct": _momentum(closes, 3),
        "ema_9": ema9,
        "ema_21": ema21,
        "trend": _trend(ema9, ema21),
        "atr_14": atr14,
        "volatility_pct": atr14 / latest * 100.0 if atr14 is not None and latest else None,
    }
    if horizon is Horizon.INTRADAY:
        result["relative_volume_20"] = _relative_volume(bars)
    return result
