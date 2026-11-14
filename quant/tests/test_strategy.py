from datetime import datetime, timedelta, timezone

from quant_engine.models import Horizon, OHLCVBar
from quant_engine.strategies.baseline import generate_signal


def test_baseline_signal_is_transparent_and_directional() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = [
        OHLCVBar(
            time=start + timedelta(days=index),
            open=100 + index - 0.5,
            high=100 + index + 1,
            low=100 + index - 1,
            close=100 + index,
            volume=1000,
        )
        for index in range(60)
    ]

    signal = generate_signal("TEST", bars, Horizon.SWING)

    assert signal.symbol == "TEST"
    assert signal.horizon is Horizon.SWING
    assert signal.direction == "bullish"
    assert signal.score > 0
    assert "EMA 20" in signal.explanation
    assert "momentum" in signal.explanation
    assert signal.current_price == bars[-1].close


def test_baseline_neutral_when_history_is_insufficient() -> None:
    one_bar = OHLCVBar(
        time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        open=10,
        high=11,
        low=9,
        close=10,
        volume=100,
    )

    signal = generate_signal("TEST", [one_bar], Horizon.SWING)

    assert signal.direction == "neutral"
    assert signal.score == 0
    assert "Insufficient historical bars" in signal.explanation
