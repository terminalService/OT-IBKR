import logging
import math
import re
from typing import Any

import httpx

from quant_engine.models import Candidate

logger = logging.getLogger(__name__)
_SYMBOL = re.compile(r"^[A-Z0-9.^=-]{1,32}$")


class OpenTerminalError(Exception):
    """OpenTerminal screener could not provide a usable candidate list."""


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalize_candidates(payload: Any) -> list[Candidate]:
    if not isinstance(payload, list):
        raise OpenTerminalError("OpenTerminal screener returned an unexpected response.")

    candidates: list[Candidate] = []
    seen: set[str] = set()
    for row in payload:
        if not isinstance(row, dict):
            logger.warning("Ignoring malformed OpenTerminal screener row.")
            continue
        raw_symbol = row.get("symbol")
        if not isinstance(raw_symbol, str):
            logger.warning("Ignoring OpenTerminal screener row without a symbol.")
            continue
        symbol = raw_symbol.strip().upper().rsplit(":", maxsplit=1)[-1]
        if not _SYMBOL.fullmatch(symbol) or symbol in seen:
            logger.warning("Ignoring invalid or duplicate OpenTerminal screener symbol.")
            continue
        seen.add(symbol)

        candidates.append(
            Candidate(
                symbol=symbol,
                name=row.get("name") if isinstance(row.get("name"), str) else None,
                price=_number(row.get("price")),
                change_percent=_number(row.get("changePercent")),
                volume=_number(row.get("volume")),
                market_cap=_number(row.get("marketCap")),
                sector=row.get("sector") if isinstance(row.get("sector"), str) else None,
                exchange=row.get("exchange") if isinstance(row.get("exchange"), str) else None,
            )
        )
    return candidates


class OpenTerminalConnector:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None

    async def get_candidates(self, limit: int) -> list[Candidate]:
        try:
            response = await self._client.get(
                f"{self._base_url}/api/screener",
                params={"market": "us", "sort": "marketCap", "dir": "desc"},
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise OpenTerminalError("OpenTerminal screener request timed out.") from exc
        except httpx.HTTPError as exc:
            raise OpenTerminalError("OpenTerminal screener is unavailable.") from exc

        if response.status_code == 429:
            raise OpenTerminalError("OpenTerminal API rate limit reached.")
        if response.is_error:
            raise OpenTerminalError(
                f"OpenTerminal screener returned HTTP {response.status_code}."
            )
        try:
            candidates = normalize_candidates(response.json())
        except (ValueError, TypeError) as exc:
            raise OpenTerminalError("OpenTerminal screener returned invalid JSON.") from exc
        if not candidates:
            raise OpenTerminalError("OpenTerminal screener returned no valid candidates.")
        return candidates[:limit]

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
