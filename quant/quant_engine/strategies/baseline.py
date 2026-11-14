from datetime import datetime, timezone
from typing import Literal

from quant_engine.features.indicators import calculate_indicators
from quant_engine.models import Horizon, OHLCVBar, ResearchSignal


def _number(indicators: dict[str, float | str | None], name: str) -> float | None:
    value = indicators.get(name)
    return value if isinstance(value, (int, float)) else None


def generate_signal(
    symbol: str,
    bars: list[OHLCVBar],
    horizon: Horizon,
    timestamp: datetime | None = None,
) -> ResearchSignal:
    if not bars:
        raise ValueError("Cannot generate a signal without historical bars.")

    indicators = calculate_indicators(bars, horizon)
    votes: list[int] = []
    reasons: list[str] = []
    direction: Literal["bullish", "bearish", "neutral"]

    if horizon is Horizon.SWING:
        fast, slow = _number(indicators, "ema_20"), _number(indicators, "ema_50")
        if fast is not None and slow is not None:
            votes.append(1 if fast > slow else -1 if fast < slow else 0)
            reasons.append(f"EMA 20 is {'above' if fast > slow else 'below' if fast < slow else 'at'} EMA 50")
        rsi = _number(indicators, "rsi_14")
        if rsi is not None:
            if 50 <= rsi <= 70:
                votes.append(1)
                reasons.append("RSI 14 is in the 50-70 positive-momentum range")
            elif 30 <= rsi < 50:
                votes.append(-1)
                reasons.append("RSI 14 is in the 30-50 negative-momentum range")
            else:
                votes.append(0)
                reasons.append("RSI 14 is outside the baseline directional ranges")
        momentum = _number(indicators, "momentum_10_pct")
        if momentum is not None:
            votes.append(1 if momentum > 0 else -1 if momentum < 0 else 0)
            reasons.append(f"10-bar momentum is {momentum:.2f}%")
    else:
        vwap = _number(indicators, "session_vwap")
        if vwap is not None:
            votes.append(1 if bars[-1].close > vwap else -1 if bars[-1].close < vwap else 0)
            reasons.append(f"Price is {'above' if bars[-1].close > vwap else 'below' if bars[-1].close < vwap else 'at'} session VWAP")
        fast, slow = _number(indicators, "ema_9"), _number(indicators, "ema_21")
        if fast is not None and slow is not None:
            votes.append(1 if fast > slow else -1 if fast < slow else 0)
            reasons.append(f"EMA 9 is {'above' if fast > slow else 'below' if fast < slow else 'at'} EMA 21")
        momentum = _number(indicators, "momentum_3_pct")
        if momentum is not None:
            votes.append(1 if momentum > 0 else -1 if momentum < 0 else 0)
            reasons.append(f"3-bar momentum is {momentum:.2f}%")

    sufficient = len(votes) >= 2
    score = round(sum(votes) / len(votes) * 100) if sufficient else 0
    direction = "bullish" if score >= 34 else "bearish" if score <= -34 else "neutral"
    if not sufficient:
        explanation = "Insufficient historical bars to produce a directional baseline; " + (
            "; ".join(reasons) if reasons else "required indicators are unavailable."
        )
    else:
        explanation = "; ".join(reasons) + f". Baseline score: {score:+d}/100."

    return ResearchSignal(
        symbol=symbol,
        timestamp=timestamp or datetime.now(timezone.utc),
        horizon=horizon,
        current_price=bars[-1].close,
        indicators=indicators,
        direction=direction,
        score=score,
        explanation=explanation,
    )
