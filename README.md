# Securities Tracker Backend

A high-performance Python backend providing real-time and historical financial data for portfolio tracking. This service integrates with **WealthSimple** for portfolio data and **Yahoo Finance** for live market ticks and historical charts via FastAPIs and WebSockets.

## 1. Objective

The primary goal of this service is to act as a data aggregator and streaming server for a financial dashboard. It:

- Synchronizes holdings and book values from WealthSimple self-directed accounts.
- Fetches real-time price updates using yfinance's WebSocket implementation.
- Provides historical OHLCV (Open, High, Low, Close, Volume) data for interactive charts.
- Broadcasts portfolio performance metrics (total value, daily change) to frontend clients via WebSockets.

## 2. Prerequisites

- **Python**: version 3.10+ recommended.
- **uv**: A fast Python package installer and resolver.
- **Environment Variables**: A `.env` file in the root directory with the following keys:
  ```env
  WS_EMAIL=your_wealthsimple_email
  WS_PASSWORD=your_wealthsimple_password
  WS_2FA_SECRET=your_totp_secret_seed  # Used to generate 2FA codes automatically
  ```

## 3. Setup and Execution

### Setting up the Environment

This project uses `uv` for dependency management. To set up your virtual environment and install dependencies:

```bash
# Install dependencies and create .venv
uv sync
```

### Running the Server

To start the FastAPI server with auto-reload enabled:

```bash
uv run uvicorn server:app --reload
```

The API will be accessible at `http://localhost:8000` and the WebSocket at `ws://localhost:8000/ws`.

---

## 4. Detailed Script & Function Overview

### `server.py`

The main entry point for the FastAPI application.

- `fetch_previous_closes()`: Asynchronously fetches the previous day's closing prices for all symbols in the portfolio to calculate daily change.
- `get_positions()`: Calculates current holdings, including profit/loss (P/L) and current market value.
- `get_portfolio()`: Aggregates position data into a high-level portfolio summary (Total Value, Daily Change %).
- `ConnectionManager`: A class to handle WebSocket lifecycles (connect, disconnect, subscribe, broadcast).
- `hooked_handle_message(msg)`: An interceptor that wraps the standard data service message handler to broadcast live price updates (`CHART_TICK`, `PORTFOLIO_UPDATE`, `POSITIONS_UPDATE`) to connected clients.
- `lifespan(app)`: Manages startup and shutdown logic:
  - Logs into WealthSimple.
  - Updates `SYMBOLS.yaml` with the latest portfolio data.
  - Pre-fetches closing prices.
  - Starts the yfinance data stream.

#### Endpoints:

- `GET /api/portfolio`: Returns total portfolio value and daily change.
- `GET /api/positions`: Returns a list of current holdings.
- `GET /api/chart/history`: Fetches historical OHLCV data with configurable timeframes (`1H`, `1D`, `1W`, `1M`).
- `WS /ws`: WebSocket endpoint for real-time updates.

### `main.py`

Contains core data processing logic and the `DataService`.

- `format_ohlcv(hist_df)`: Normalizes yfinance historical data into a clean JSON-ready format with Unix timestamps.
- `read_symbol_yaml()`: Utility to read the local `SYMBOLS.yaml` cache.
- `load_portfolio()`: High-level loader that prefers WealthSimple data but falls back to the local YAML file.
- `DataService`:
  - `preload_prices()`: Uses `yf.download` to quickly fetch initial prices for all symbols on startup.
  - `handle_message(msg)`: The primary callback for incoming yfinance WebSocket market ticks.
  - `retry_missing_prices()`: A robust retry mechanism for symbols that failed to preload via standard REST calls.
  - `start_stream()`: Initializes the `AsyncWebSocket` stream for continuous market data.

### `wealthsimple_integration.py`

Handles the connection and data extraction from WealthSimple.

- `WealthSimpleManager`:
  - `get_otp_code()`: Generates a 6-digit TOTP code using the `WS_2FA_SECRET` from `.env`.
  - `login()`: Handles the multi-step authentication process (password + 2FA).
- `get_wealthsimple_portfolio(manager)`: The primary integration function. It:
  - Fetches all open self-directed accounts.
  - Aggregates holdings across accounts.
  - Resolves WealthSimple internal security IDs into standard ticker symbols.
  - Calculates the total book value and total shares for each unique security.

### `helper.py`

Normalization utilities for symbol mapping.

- `to_frontend_symbol(sym)`: Maps backend symbols (like `BTC-USD`) to a consistent frontend naming convention (`BTC-CAD`).
- `to_backend_symbol(sym)`: Maps various ticker formats (like `BTC/USDT` or `BTC`) to the specific format expected by the backend and yfinance (`BTC-CAD`).

### `src/ws_api/` (WealthSimple API Wrapper)

#### Fork of wsimple with some edits.

A comprehensive internal library for interacting with WealthSimple's GraphQL and OAuth APIs.

- **`wealthsimple_api.py`**:
  - `WealthsimpleAPIBase`: Implements low-level HTTP/GraphQL request handling, session persistence, and OAuth token management.
  - `WealthsimpleAPI`: Provides high-level methods for fetching accounts, balances, historical financials, activities, and positions.
- **`formatters.py`**: Contains complex logic for turning raw API responses into human-readable descriptions for accounts and activities (e.g., formatting "DIY_BUY" as "Buy").
- **`session.py`**: Defines data structures for OAuth and session state.
- **`graphql_queries.py`**: A central repository for the GraphQL query strings used to interact with WealthSimple.
- **`exceptions.py`**: Custom error classes for handling login failures, OTP requirements, and API errors.
