from datetime import datetime, timedelta, timezone

from quant_engine.features.indicators import calculate_indicators, vwap_by_session
from quant_engine.models import Horizon, OHLCVBar


def bars(closes: list[float], start: datetime | None = None) -> list[OHLCVBar]:
    beginning = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        OHLCVBar(
            time=beginning + timedelta(minutes=5 * index),
            open=close - 0.5,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=100 + index,
        )
        for index, close in enumerate(closes)
    ]


def test_swing_indicators_calculate_ema_momentum_and_atr() -> None:
    result = calculate_indicators(bars([100 + index for index in range(60)]), Horizon.SWING)

    assert result["ema_20"] is not None
    assert result["ema_50"] is not None
    assert result["momentum_10_pct"] > 0
    assert result["atr_14"] == 2
    assert result["trend"] == "up"


def test_rsi_handles_rising_falling_and_flat_series() -> None:
    rising = calculate_indicators(bars([float(10 + i) for i in range(15)]), Horizon.SWING)
    falling = calculate_indicators(bars([float(30 - i) for i in range(15)]), Horizon.SWING)
    flat = calculate_indicators(bars([20.0] * 15), Horizon.SWING)

    assert rising["rsi_14"] == 100
    assert falling["rsi_14"] == 0
    assert flat["rsi_14"] == 50


def test_vwap_resets_on_new_session_date() -> None:
    start = datetime(2026, 3, 2, 14, 30, tzinfo=timezone.utc)
    input_bars = [
        OHLCVBar(time=start, open=10, high=10, low=10, close=10, volume=1),
        OHLCVBar(time=start + timedelta(minutes=5), open=20, high=20, low=20, close=20, volume=3),
        OHLCVBar(
            time=start + timedelta(days=1),
            open=30,
            high=30,
            low=30,
            close=30,
            volume=2,
        ),
        OHLCVBar(
            time=start + timedelta(days=1, minutes=5),
            open=40,
            high=40,
            low=40,
            close=40,
            volume=2,
        ),
    ]

    assert vwap_by_session(input_bars) == [10, 17.5, 30, 35]
