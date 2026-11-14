# OpenTerminal Quant Research Service

An independent Python service that reuses OpenTerminal's existing screener for candidate discovery and requests historical bars from IBKR. It produces transparent research signals and stores them in a separate SQLite database.

**Research-only:** the service uses the IBKR API in read-only mode and contains no order placement, modification, or cancellation functionality. Signals are not recommendations and do not claim predictive or profitable performance. OpenTerminal's public market data may be delayed or incomplete and is never treated as execution-grade data.

## Requirements

- Python 3.11 or newer
- OpenTerminal running locally (its Express API defaults to `http://127.0.0.1:4000`)
- TWS or IB Gateway configured for **paper trading**, with API access enabled and Read-Only API access selected

## Install

From the repository root:

```bash
cd quant
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
cp .env.example .env
```

Edit `.env` if needed. The default IBKR endpoint is TWS paper trading at `127.0.0.1:7497`; for IB Gateway paper trading set `IBKR_PORT=4002`. `IBKR_CLIENT_ID` must be unique among clients connected to the same TWS/Gateway session.

The Python service is independent of the Node application and uses the existing `GET /api/screener` API route. Do not point it at the Next.js web server unless the Express API is intentionally hosted elsewhere; configure `OPENTERMINAL_API_URL` to the Express API origin.

## TWS / IB Gateway setup

1. Start TWS or IB Gateway and log in to a **paper trading** account.
2. In TWS, open **File → Global Configuration → API → Settings**. In IB Gateway, open **Configure → Settings → API → Settings**.
3. Enable socket clients and allow localhost connections. Keep **Read-Only API** enabled.
4. Confirm the paper socket port: TWS paper uses `7497`; IB Gateway paper uses `4002`. Ensure the configured port is not the live-trading port.
5. Leave the API session running while using this service. The service does not log in to TWS/Gateway or manage brokerage credentials.

The connector opens a connection when a scan requests data, reuses it through that scan, and disconnects when the Python service shuts down. `GET /ibkr/status` reports the current connection state; it does not initiate a connection. IBKR account-summary tags can be requested internally, but account values are not persisted, logged, or returned by an API endpoint.

## Configure and run

Configuration is loaded from environment variables or `quant/.env`:

| Variable | Default | Description |
|---|---|---|
| `OPENTERMINAL_API_URL` | `http://127.0.0.1:4000` | Existing OpenTerminal Express API base URL |
| `OPENTERMINAL_TIMEOUT_SECONDS` | `10` | Screener request timeout |
| `IBKR_HOST` | `127.0.0.1` | TWS/Gateway host |
| `IBKR_PORT` | `7497` | Paper socket port; use `4002` for Gateway |
| `IBKR_CLIENT_ID` | `31` | Client ID for this connection |
| `IBKR_TIMEOUT_SECONDS` | `8` | Connect and historical-data request timeout |
| `DATABASE_PATH` | `./data/quant.db` | Separate quant SQLite database (relative to `quant/`) |
| `SWING_DURATION` / `SWING_BAR_SIZE` | `2 Y` / `1 day` | Swing historical-data request |
| `INTRADAY_DURATION` / `INTRADAY_BAR_SIZE` | `5 D` / `5 mins` | Intraday historical-data request |
| `DAY_TRADING_DURATION` / `DAY_TRADING_BAR_SIZE` | `1 D` / `5 mins` | Day-trading historical-data request |

Start the service from the `quant/` directory:

```bash
uvicorn quant_engine.app.main:app --host 127.0.0.1 --port 8000
```

Interactive API documentation is available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

## API

- `GET /health` — service and SQLite health; independent of IBKR availability.
- `GET /ibkr/status` — current IBKR socket connection state and configured host/port; no account information.
- `POST /scan?horizon=swing&limit=10` — discovers up to 50 candidates from the existing US screener, retrieves IBKR historical bars, calculates indicators, generates research signals, and persists the scan and results. Valid horizons are `swing`, `intraday`, and `day_trading`; `limit` is 1–50.
- `GET /signals?horizon=swing&limit=50` — returns persisted signals. `horizon` is optional and `limit` is 1–200.

Unavailable OpenTerminal data returns HTTP 502; unavailable IBKR connectivity returns HTTP 503. If individual symbols have no usable bars, the scan completes with those symbols listed under `failed_symbols`; no signal is fabricated for them. No endpoint can place, modify, or cancel an order.

## Baseline calculations

The baseline emits `bullish`, `bearish`, or `neutral` research directions and a transparent score between -100 and 100. EMA relationship, price relative to session VWAP, RSI ranges, and recent momentum contribute directional votes as available. An explanation lists the factors considered. Indicators with insufficient history are `null`; fewer than two usable directional votes yields a neutral, zero-score result.

- **Swing:** daily bars, EMA 20/50, RSI 14, ATR 14, 10-bar momentum, and EMA trend.
- **Intraday:** five-minute bars, regular-session VWAP, EMA 9/21, 3-bar momentum, ATR-based volatility, and relative volume when enough prior bars are available.
- **Day trading:** five-minute bars, regular-session VWAP, EMA 9/21, 3-bar momentum, and ATR-based volatility.

The IBKR historical requests use regular trading hours. VWAP resets by bar session date and is calculated from typical price `(high + low + close) / 3` weighted by volume. These are basic research calculations, not validated trading strategies.

## Tests

The test suite mocks both external services; a running TWS/Gateway session is not needed:

```bash
pytest
```

## Troubleshooting

- **OpenTerminal unavailable:** start the existing Node application with `npm run dev`, then check `http://127.0.0.1:4000/api/status` and confirm `OPENTERMINAL_API_URL` points to the Express API.
- **IBKR connection refused or times out:** verify TWS/Gateway is running and logged in to paper trading, socket clients are enabled, Read-Only API is on, and the host/port/client ID match the configuration.
- **No history or qualification failures:** check the IBKR API market-data permissions and contract availability. The service fails the affected symbol rather than using OpenTerminal's discovery quote as a substitute.
- **Port/client ID conflicts:** close duplicate sessions or configure a distinct client ID; use only the paper port (`7497` for TWS or `4002` for Gateway).
- **Missing scan candidates:** OpenTerminal's screener is subject to its upstream provider, rate limits, and cache. Retry later; an empty or malformed response does not produce fabricated candidates.

## Limitations

The initial connector qualifies US stock contracts through SMART in USD. Historical bar availability depends on the connected IBKR account's subscriptions and API permissions. Screener values are used only for discovery, the baseline has not been performance-validated, and persisted records are local research output—not brokerage account or order state.
