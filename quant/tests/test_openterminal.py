import httpx
import pytest

from quant_engine.connectors.openterminal import (
    OpenTerminalConnector,
    OpenTerminalError,
    normalize_candidates,
)


def test_normalization_cleans_symbols_and_invalid_market_values() -> None:
    candidates = normalize_candidates(
        [
            {
                "symbol": " nasdaq:aapl ",
                "name": "Apple",
                "price": "192.5",
                "changePercent": "invalid",
                "volume": 1000,
                "marketCap": float("inf"),
                "sector": "Technology",
            },
            {"symbol": "AAPL", "name": "Duplicate"},
            {"symbol": "bad symbol"},
            None,
        ]
    )

    assert len(candidates) == 1
    assert candidates[0].symbol == "AAPL"
    assert candidates[0].price == 192.5
    assert candidates[0].change_percent is None
    assert candidates[0].market_cap is None


def test_normalization_rejects_non_list_response() -> None:
    with pytest.raises(OpenTerminalError):
        normalize_candidates({"data": []})


@pytest.mark.asyncio
async def test_connector_uses_existing_screener_route_and_normalizes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=[{"symbol": "NYSE:XYZ", "price": 12, "changePercent": 1.5}],
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = OpenTerminalConnector("http://terminal:4000/", client=client)
    try:
        candidates = await connector.get_candidates(2)
    finally:
        await connector.close()

    assert candidates[0].symbol == "XYZ"
    assert requests[0].url.path == "/api/screener"
    assert requests[0].url.params["market"] == "us"


@pytest.mark.asyncio
async def test_connector_surfaces_api_rate_limit() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(429))
    )
    connector = OpenTerminalConnector("http://terminal:4000", client=client)
    try:
        with pytest.raises(OpenTerminalError, match="rate limit"):
            await connector.get_candidates(1)
    finally:
        await connector.close()
