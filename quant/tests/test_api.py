from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from quant_engine.config import Settings
from quant_engine.connectors.ibkr import IBKRConnectionError
from quant_engine.models import (
    Candidate,
    HistoricalDataMetadata,
    Horizon,
    OHLCVBar,
)
from quant_engine.app.main import create_app


class FakeOpenTerminal:
    async def get_candidates(self, limit: int) -> list[Candidate]:
        return [
            Candidate(symbol="TEST", name="Test Co", price=100),
        ][:limit]

    async def close(self) -> None:
        pass


class FakeIBKR:
    def status(self) -> dict[str, bool | str | int]:
        return {"connected": True, "host": "127.0.0.1", "port": 7497, "readonly": True}

    async def fetch_history(self, symbol: str, horizon: Horizon):
        now = datetime.now(timezone.utc)
        bars = [
            OHLCVBar(
                time=now - timedelta(days=60 - index),
                open=100 + index - 0.5,
                high=100 + index + 1,
                low=100 + index - 1,
                close=100 + index,
                volume=1000,
            )
            for index in range(60)
        ]
        metadata = HistoricalDataMetadata(
            symbol=symbol,
            bar_size="1 day",
            duration="2 Y",
            use_rth=True,
            bar_count=len(bars),
            start_time=bars[0].time,
            end_time=bars[-1].time,
        )
        return bars, metadata

    async def disconnect(self) -> None:
        pass


class FailedIBKR(FakeIBKR):
    async def fetch_history(self, symbol: str, horizon: Horizon):
        raise IBKRConnectionError("Could not connect to the configured TWS or IB Gateway instance.")


def test_health_status_scan_and_persisted_signals(tmp_path) -> None:
    settings = Settings(database_path=str(tmp_path / "quant.db"))
    app = create_app(
        settings=settings,
        openterminal=FakeOpenTerminal(),
        ibkr=FakeIBKR(),
    )

    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "healthy"
        status = client.get("/ibkr/status").json()
        assert status["connected"] is True
        assert status["readonly"] is True
        assert "account" not in status

        response = client.post("/scan?horizon=swing&limit=1")
        assert response.status_code == 200
        payload = response.json()
        assert payload["candidates"] == 1
        assert payload["signals"][0]["symbol"] == "TEST"
        assert payload["signals"][0]["direction"] == "bullish"

        stored = client.get("/signals?horizon=swing").json()
        assert len(stored) == 1
        assert stored[0]["scan_id"] == payload["scan_id"]
        assert stored[0]["indicators"]["ema_20"] is not None
        assert client.post("/scan?horizon=unknown").status_code == 422
        assert client.post("/scan?limit=51").status_code == 422


def test_scan_fails_safely_when_ibkr_is_unavailable(tmp_path) -> None:
    app = create_app(
        settings=Settings(database_path=str(tmp_path / "quant.db")),
        openterminal=FakeOpenTerminal(),
        ibkr=FailedIBKR(),
    )

    with TestClient(app) as client:
        response = client.post("/scan?horizon=swing")

    assert response.status_code == 503
    assert "Could not connect" in response.json()["detail"]
