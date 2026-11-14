from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request

from quant_engine.config import Settings, get_settings
from quant_engine.connectors.ibkr import (
    IBKRConnectionError,
    IBKRConnector,
    IBKRDataError,
)
from quant_engine.connectors.openterminal import (
    OpenTerminalConnector,
    OpenTerminalError,
)
from quant_engine.models import (
    Horizon,
    ResearchSignal,
    ScanResponse,
    StoredSignal,
    SymbolFailure,
)
from quant_engine.storage.repository import SignalRepository
from quant_engine.strategies.baseline import generate_signal


def create_app(
    *,
    settings: Settings | None = None,
    openterminal: OpenTerminalConnector | None = None,
    ibkr: IBKRConnector | None = None,
    repository: SignalRepository | None = None,
) -> FastAPI:
    configured = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.openterminal = openterminal or OpenTerminalConnector(
            configured.openterminal_api_url,
            configured.openterminal_timeout_seconds,
        )
        app.state.ibkr = ibkr or IBKRConnector(configured)
        app.state.repository = repository or SignalRepository(configured.database_path)
        yield
        await app.state.ibkr.disconnect()
        await app.state.openterminal.close()
        app.state.repository.close()

    app = FastAPI(
        title="OpenTerminal Quant Research Service",
        description="Research-only indicators and signals; no trading operations are available.",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health(request: Request) -> dict[str, str]:
        if not request.app.state.repository.healthy():
            raise HTTPException(status_code=503, detail="Quant storage is unavailable.")
        return {"status": "healthy", "service": "quant-research"}

    @app.get("/ibkr/status")
    async def ibkr_status(request: Request) -> dict[str, str | int | bool]:
        return request.app.state.ibkr.status()

    @app.post("/scan", response_model=ScanResponse)
    async def scan(
        request: Request,
        horizon: Horizon = Horizon.SWING,
        limit: Annotated[int, Query(ge=1, le=50)] = 10,
    ) -> ScanResponse:
        repo: SignalRepository = request.app.state.repository
        scan_id = repo.begin_scan(horizon)
        candidates_count = 0
        signals: list[ResearchSignal] = []
        failures: list[SymbolFailure] = []
        try:
            candidates = await request.app.state.openterminal.get_candidates(limit)
            candidates_count = len(candidates)
            repo.save_candidates(scan_id, candidates)
            for candidate in candidates:
                try:
                    bars, metadata = await request.app.state.ibkr.fetch_history(
                        candidate.symbol, horizon
                    )
                except IBKRConnectionError:
                    raise
                except IBKRDataError:
                    failures.append(
                        SymbolFailure(
                            symbol=candidate.symbol,
                            reason="IBKR did not return usable historical data.",
                        )
                    )
                    continue
                signal = generate_signal(candidate.symbol, bars, horizon)
                repo.save_result(scan_id, metadata, signal)
                signals.append(signal)
            repo.finish_scan(
                scan_id,
                status="completed",
                candidate_count=candidates_count,
                signal_count=len(signals),
                failure_count=len(failures),
            )
        except OpenTerminalError as exc:
            repo.finish_scan(
                scan_id,
                status="failed",
                candidate_count=candidates_count,
                signal_count=len(signals),
                failure_count=len(failures) + 1,
            )
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except IBKRConnectionError as exc:
            repo.finish_scan(
                scan_id,
                status="failed",
                candidate_count=candidates_count,
                signal_count=len(signals),
                failure_count=len(failures) + 1,
            )
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception:
            repo.finish_scan(
                scan_id,
                status="failed",
                candidate_count=candidates_count,
                signal_count=len(signals),
                failure_count=len(failures) + 1,
            )
            raise
        return ScanResponse(
            scan_id=scan_id,
            horizon=horizon,
            candidates=candidates_count,
            signals=signals,
            failed_symbols=failures,
        )

    @app.get("/signals", response_model=list[StoredSignal])
    async def signals(
        request: Request,
        horizon: Horizon | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> list[StoredSignal]:
        rows = request.app.state.repository.list_signals(horizon, limit)
        return [StoredSignal.model_validate(row) for row in rows]

    return app


app = create_app()
