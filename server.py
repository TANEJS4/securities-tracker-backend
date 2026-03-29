import asyncio
import json
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict
import yfinance as yf
from contextlib import asynccontextmanager
import logging

from main import DataService, SYMBOLS, format_ohlcv

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)


def to_frontend_symbol(sym: str) -> str:
    if sym == "BTC-USD":
        return "BTC/USDT"
    if sym == "ETH-USD":
        return "ETH/USDT"
    return sym


def to_backend_symbol(sym: str) -> str:
    if sym == "BTC/USDT":
        return "BTC-USD"
    if sym == "ETH/USDT":
        return "ETH-USD"
    return sym


PREVIOUS_CLOSES = {}


async def fetch_previous_closes():
    def _fetch():
        for sym in SYMBOLS:
            try:
                info = yf.Ticker(sym).fast_info
                PREVIOUS_CLOSES[sym] = info["previousClose"]
            except Exception:
                PREVIOUS_CLOSES[sym] = SYMBOLS[sym].get("book_value", 0)

    await asyncio.get_running_loop().run_in_executor(None, _fetch)


data_service = DataService(SYMBOLS)


def get_positions() -> List[Dict]:
    positions = []
    for sym, info in SYMBOLS.items():
        shares = info.get("shares")
        book_price = info.get("book_value")
        if shares is None or book_price is None:
            continue

        current_data = data_service.latest_data.get(sym, {})
        current_price = current_data.get("price", 0.0)
        if current_price == "N/A" or not isinstance(current_price, (int, float)):
            current_price = 0.0

        pl = round((current_price - book_price) * shares, 2)
        performance = (
            ((current_price - book_price) / book_price) * 100 if book_price else 0.0
        )

        positions.append(
            {
                "symbol": sym,  # to_frontend_symbol(sym),
                "currentPrice": round(current_price, 2),
                "bookPrice": book_price,
                "shares": shares,
                "pl": pl,
                # "performance": performance,
            }
        )
    return positions


def get_portfolio() -> Dict:
    positions = get_positions()
    total_value = sum(p["currentPrice"] * p["shares"] for p in positions)

    daily_change = 0.0
    for p in positions:
        # backend_sym = to_backend_symbol(p["symbol"])
        backend_sym = p.get("symbol")
        prev_close = PREVIOUS_CLOSES.get(backend_sym, p["bookPrice"])
        daily_change += (p["currentPrice"] - prev_close) * p["shares"]

    prev_total_value = total_value - daily_change
    daily_change_percent = (
        (daily_change / prev_total_value) * 100 if prev_total_value else 0.0
    )

    return {
        "totalValue": total_value,
        "dailyChange": daily_change,
        "dailyChangePercent": daily_change_percent,
        # "goalPercentage": 65.0,
    }


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[WebSocket, set] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.subscriptions[websocket] = set()

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.subscriptions:
            del self.subscriptions[websocket]

    async def subscribe(self, websocket: WebSocket, channels: List[str]):
        if websocket in self.subscriptions:
            self.subscriptions[websocket].update(channels)

    async def broadcast(self, channel: str, message: dict):
        for connection in list(self.active_connections):
            if channel in self.subscriptions.get(connection, set()):
                try:
                    await connection.send_json(message)
                except Exception:
                    self.disconnect(connection)


manager = ConnectionManager()

# Hook into DataService to broadcast live ticks
original_handle_message = data_service.handle_message


async def hooked_handle_message(msg: dict):
    # Call the original method to update DataService's state
    await original_handle_message(msg)

    sym = msg.get("id")
    price = msg.get("price")
    if sym and price is not None:
        frontend_sym = sym  # to_frontend_symbol(sym)

        # 1. Broadcast the chart tick
        tick_msg = {
            "type": "CHART_TICK",
            "payload": {
                "time": int(time.time()),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": msg.get("dayVolume", 0),
            },
        }
        await manager.broadcast(f"chart_ticks:{frontend_sym}", tick_msg)

        # 2. Broadcast portfolio updates
        await manager.broadcast(
            "portfolio_updates",
            {"type": "PORTFOLIO_UPDATE", "payload": get_portfolio()},
        )

        # 3. Broadcast positions updates
        await manager.broadcast(
            "positions_updates",
            {"type": "POSITIONS_UPDATE", "payload": get_positions()},
        )


data_service.handle_message = hooked_handle_message


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start up
    await fetch_previous_closes()
    asyncio.create_task(data_service.start_stream())
    yield
    # Shut down (nothing specific to await)


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/portfolio")
def api_portfolio():
    return get_portfolio()


@app.get("/api/startup_portflio")
def startup_portflio():
    return 10000


@app.get("/api/symbol_name")
async def api_symbol_name(symbol: str):
    def _fetch_name():
        try:
            info = yf.Ticker(symbol).info
            return info.get("longName") or info.get("shortName") or symbol
        except Exception:
            return symbol

    name = await asyncio.get_running_loop().run_in_executor(None, _fetch_name)
    return {"name": f"{symbol}: {name}"}


@app.get("/api/positions")
def api_positions():
    return get_positions()


@app.get("/api/chart/history")
def api_chart_history(symbol: str, timeframe: str = "1H"):
    yf_symbol = symbol

    interval = "1m"
    period = "1d"
    slice_count = 0

    # if timeframe == "15m":
    #     interval = "1m"
    #     period = "5d"
    # slice_count = 150
    if timeframe == "1H":
        interval = "1m"
        period = "1d"
        slice_count = 65
    elif timeframe == "1D":
        interval = "5m"
        period = "1d"
    elif timeframe == "1W":
        interval = "30m"
        period = "5d"
        # slice_count = 240
    elif timeframe == "1M":
        interval = "15m"
        period = "1mo"
        # slice_count = 240
    else:
        raise Exception(f"Invalid input interval = {interval}, period = {period}")

    try:
        hist_df = yf.Ticker(yf_symbol).history(
            period=period, interval=interval, timeout=30
        )
        if hist_df.empty:
            return []
        formatted_df = format_ohlcv(hist_df)
        records = formatted_df.to_dict(orient="records")
        # slice_count = max(240, len(records))
        logging.info(f"[CHART_HISTORY] {len(records)} {formatted_df}")
        if slice_count:
            return records[-slice_count:]
        return records
    except Exception:
        return []


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("action") == "subscribe":
                    channels = msg.get("channels", [])
                    await manager.subscribe(websocket, channels)
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
