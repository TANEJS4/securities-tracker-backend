import asyncio
import time


from yfinance import AsyncWebSocket, download, Ticker

from src.utils.logger import logger

from src.utils.transform import SYMBOLS
from src.websocket.socket import manager

import config
from src.route.api import get_portfolio, get_positions


#! TEST
# SYMBOLS = {
#     "BTC-CAD": {"book_value": 129328.97, "shares": 0.011184},
#     "NFLX": {"book_value": 104.76, "shares": 40.0},
#     "AAPL": {"book_value": 233.79, "shares": 5.0013},
#     "MSFT": {"book_value": 543.0, "shares": 5.0},
# }


# ══════════════════════════════════════════════
#  DATA SERVICE
# ══════════════════════════════════════════════
class DataService:
    # handles all data fetching: preload, websocket streaming, and retries

    def __init__(self, symbols=None):
        self.symbols = symbols or SYMBOLS
        self.latest_data = {}
        self.previous_prices = {}

    def preload_prices(self):
        # Fetch initial 1-day/1-min OHLCV data for all symbols.

        symbols = list(self.symbols.keys())
        logger.info(f"Preloading initial data for {symbols}")
        tickers = download(
            symbols, period="1d", interval="1m", progress=False, threads=True
        )
        if isinstance(tickers, tuple) or tickers.empty:
            logger.warning("Failed to fetch initial data")
            return

        latest_row = tickers.tail(1)
        for sym in symbols:
            try:
                price = float(latest_row["Close"][sym].iloc[0])
                if price != price:
                    raise ValueError("NaN price received")
                volume = int(latest_row["Volume"][sym].iloc[0])

                self.latest_data[sym] = {"price": price, "volume": volume}
                self.previous_prices[sym] = price

            except Exception as e:
                logger.warning(
                    f"Preload failed for {sym}: {e}",
                )
                self.latest_data[sym] = {"price": "N/A", "volume": "N/A"}
                self.previous_prices[sym] = None
        logger.info(
            f"self.latest_data: {self.latest_data}, self.previous_prices: { self.previous_prices}"
        )
        setattr(config, "previous_closes", self.previous_prices)
        setattr(config, "latest_data", self.latest_data)
        return self.latest_data, self.previous_prices

    async def handle_message(self, msg: dict):
        # websocker: updates previous_prices and latest_data
        symbol = msg.get("id", None)
        price = msg.get("price", 0)
        volume = msg.get("dayVolume", 0)

        prev_price = self.latest_data.get(symbol, {}).get("price")
        self.previous_prices[symbol] = prev_price

        self.latest_data[symbol] = {"price": price, "volume": volume}
        logger.info(f"handle_message updated - self.latest_data : {self.latest_data}")

    async def retry_missing_prices(
        self, symbols: list, retries: int = 5, delay: float = 5.0
    ):
        #  retry fetching prices for symbols that failed preload! IMPORTANT
        loop = asyncio.get_running_loop()
        pending = list(symbols)

        for attempt in range(retries):
            still_missing = []
            for sym in pending:
                if isinstance(self.latest_data.get(sym, {}).get("price"), (int, float)):
                    continue
                try:

                    def _fetch(s=sym):
                        info = Ticker(s).fast_info
                        price = info["lastPrice"]
                        if price != price or price is None:
                            raise ValueError("NaN/None price from fast_info")
                        return float(price)

                    price = await loop.run_in_executor(None, _fetch)
                    self.latest_data[sym] = {
                        "price": price,
                        "volume": self.latest_data[sym].get("volume", "N/A"),
                    }
                    self.previous_prices[sym] = price
                    logger.info(f"Retry succeeded for {sym}: {price}")
                except Exception as e:
                    logger.warning(f"Retry {attempt+1}/{retries}failed for {sym}: {e}")
                    still_missing.append(sym)

            pending = still_missing
            if not pending:
                break
            await asyncio.sleep(delay)

    async def start_stream(self):
        # entry point for websocker: preload data, open websocket, start listening
        self.preload_prices()

        async with AsyncWebSocket(verbose=False) as ws:
            await ws.subscribe(list(self.symbols.keys()))

            listener = asyncio.create_task(
                ws.listen(message_handler=self.handle_message)
            )
            retrier = asyncio.create_task(
                self.retry_missing_prices(
                    [
                        s
                        for s in self.symbols
                        if self.latest_data.get(s, {}).get("price") == "N/A"
                    ]
                )
            )
            await listener


data_service = DataService(SYMBOLS)

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
            {
                "type": "PORTFOLIO_UPDATE",
                "payload": get_portfolio(
                    getattr(config, "previous_closes", data_service.previous_prices)
                ),
            },
        )

        # 3. Broadcast positions updates
        await manager.broadcast(
            "positions_updates",
            {"type": "POSITIONS_UPDATE", "payload": get_positions()},
        )
