import asyncio
from datetime import date, datetime, time, timezone
from typing import Any

from ib_async import IB, Stock

from quant_engine.config import Settings
from quant_engine.models import HistoricalDataMetadata, Horizon, OHLCVBar


class IBKRConnectionError(Exception):
    """IBKR is not connected or cannot be reached."""


class IBKRDataError(Exception):
    """IBKR could not provide usable historical data."""


def _bar_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    elif isinstance(value, str):
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            for pattern in ("%Y%m%d", "%Y%m%d %H:%M:%S"):
                try:
                    parsed = datetime.strptime(text, pattern)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError("IBKR returned an unrecognized bar timestamp.")
    else:
        raise ValueError("IBKR returned an unrecognized bar timestamp.")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class IBKRConnector:
    def __init__(self, settings: Settings, ib: IB | None = None) -> None:
        self._settings = settings
        self._ib = ib or IB()
        self._lock = asyncio.Lock()

    def status(self) -> dict[str, Any]:
        return {
            "connected": self._ib.isConnected(),
            "host": self._settings.ibkr_host,
            "port": self._settings.ibkr_port,
            "readonly": True,
        }

    async def connect(self) -> None:
        if self._ib.isConnected():
            return
        async with self._lock:
            if self._ib.isConnected():
                return
            try:
                await asyncio.wait_for(
                    self._ib.connectAsync(
                        self._settings.ibkr_host,
                        self._settings.ibkr_port,
                        clientId=self._settings.ibkr_client_id,
                        timeout=self._settings.ibkr_timeout_seconds,
                        readonly=True,
                    ),
                    timeout=self._settings.ibkr_timeout_seconds + 1,
                )
            except (asyncio.TimeoutError, OSError, ConnectionError) as exc:
                raise IBKRConnectionError(
                    "Could not connect to the configured TWS or IB Gateway instance."
                ) from exc
            except Exception as exc:
                raise IBKRConnectionError(
                    "Could not connect to the configured TWS or IB Gateway instance."
                ) from exc
            if not self._ib.isConnected():
                raise IBKRConnectionError("IBKR connection did not become active.")

    async def get_account_summary_tags(self) -> tuple[str, ...]:
        """Refresh permitted summary data without retaining account values."""
        await self.connect()
        try:
            rows = await asyncio.wait_for(
                self._ib.reqAccountSummaryAsync(),
                timeout=self._settings.ibkr_timeout_seconds,
            )
        except Exception as exc:
            raise IBKRDataError("IBKR account summary is unavailable.") from exc
        return tuple(sorted({str(row.tag) for row in rows}))

    async def fetch_history(
        self, symbol: str, horizon: Horizon
    ) -> tuple[list[OHLCVBar], HistoricalDataMetadata]:
        await self.connect()
        duration, bar_size = self._bar_settings(horizon)
        try:
            contract = Stock(symbol, "SMART", "USD")
            qualified = await asyncio.wait_for(
                self._ib.qualifyContractsAsync(contract),
                timeout=self._settings.ibkr_timeout_seconds,
            )
            if not qualified:
                raise IBKRDataError(f"IBKR could not qualify {symbol}.")
            raw_bars = await asyncio.wait_for(
                self._ib.reqHistoricalDataAsync(
                    qualified[0],
                    endDateTime="",
                    durationStr=duration,
                    barSizeSetting=bar_size,
                    whatToShow="TRADES",
                    useRTH=True,
                    formatDate=2,
                    keepUpToDate=False,
                ),
                timeout=self._settings.ibkr_timeout_seconds,
            )
        except IBKRDataError:
            raise
        except asyncio.TimeoutError as exc:
            raise IBKRDataError(f"IBKR historical data request timed out for {symbol}.") from exc
        except Exception as exc:
            if not self._ib.isConnected():
                raise IBKRConnectionError("IBKR connection was lost during the scan.") from exc
            raise IBKRDataError(f"IBKR historical data request failed for {symbol}.") from exc

        if not isinstance(raw_bars, (list, tuple)):
            raise IBKRDataError(f"IBKR returned malformed historical data for {symbol}.")
        bars: list[OHLCVBar] = []
        for raw in raw_bars:
            try:
                bars.append(
                    OHLCVBar(
                        time=_bar_datetime(raw.date),
                        open=float(raw.open),
                        high=float(raw.high),
                        low=float(raw.low),
                        close=float(raw.close),
                        volume=max(float(raw.volume), 0.0),
                    )
                )
            except (TypeError, ValueError):
                continue
        if not bars:
            raise IBKRDataError(f"IBKR returned no usable historical bars for {symbol}.")
        metadata = HistoricalDataMetadata(
            symbol=symbol,
            bar_size=bar_size,
            duration=duration,
            use_rth=True,
            bar_count=len(bars),
            start_time=bars[0].time,
            end_time=bars[-1].time,
        )
        return bars, metadata

    def _bar_settings(self, horizon: Horizon) -> tuple[str, str]:
        if horizon is Horizon.SWING:
            return self._settings.swing_duration, self._settings.swing_bar_size
        if horizon is Horizon.INTRADAY:
            return self._settings.intraday_duration, self._settings.intraday_bar_size
        return self._settings.day_trading_duration, self._settings.day_trading_bar_size

    async def disconnect(self) -> None:
        if self._ib.isConnected():
            self._ib.disconnect()
