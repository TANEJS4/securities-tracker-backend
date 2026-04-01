# ══════════════════════════════════════════════
#  IMPORTS
# ══════════════════════════════════════════════
import asyncio
import yaml

import logging
import pandas as pd

import yfinance as yf
from yfinance import AsyncWebSocket, download, Ticker
from wealthsimple_integration import get_wealthsimple_portfolio


logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)


def format_ohlcv(hist_df):
    # open,high,low, close, volume - ohlcv
    # Convert a yfinance history DataFrame to lightweight-charts format.

    # Input:  DataFrame with DatetimeTZ index ('Datetime'/'Date') and
    #         capitalized columns (Open, High, Low, Close, Volume).
    #         Use yfinance `Ticker.history()` — NOT `yfinance.download()`.
    #         download() returns a multi-level column index incompatible with
    #         this function's column-rename logic.
    # Output: DataFrame with columns [time, open, high, low, close, volume]
    #         where `time` is a Unix integer (seconds, UTC).

    df = hist_df.copy()

    df = df.reset_index()

    time_col = "Datetime" if "Datetime" in df.columns else "Date"
    df = df.rename(
        columns={
            time_col: "time",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )

    # Convert to UTC Unix seconds
    if hasattr(df["time"].dt, "tz") and df["time"].dt.tz is not None:
        df["time"] = df["time"].dt.tz_convert("UTC")
    df["time"] = df["time"].astype("int64") // 10**9

    return df[["time", "open", "high", "low", "close", "volume"]]


def read_symbol_yaml():
    try:
        with open("./SYMBOLS.yaml", "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        log.warning(f"Could not read SYMBOLS.yaml: {e}")
        return {}


def load_portfolio():
    #  load portfolio from WealthSimple
    try:
        log.info("Attempting to load portfolio from WealthSimple...")
        ws_portfolio = get_wealthsimple_portfolio()
        if ws_portfolio:
            log.info(
                f"Successfully loaded portfolio from WealthSimple with {len(ws_portfolio)} symbols.",
            )
            return ws_portfolio
    except Exception as e:
        log.error(f"Failed to load portfolio from WealthSimple: {e}")

    log.info("Falling back to local SYMBOLS.yaml")
    return read_symbol_yaml()


SYMBOLS = load_portfolio()

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

    def __init__(self, symbols):
        self.symbols = symbols
        self.latest_data = {}
        self.previous_prices = {}

    def preload_prices(self):
        # Fetch initial 1-day/1-min OHLCV data for all symbols.

        symbols = list(self.symbols.keys())
        log.debug(f"Preloading initial data for {symbols}")
        tickers = download(
            symbols, period="1d", interval="1m", progress=False, threads=True
        )
        if isinstance(tickers, tuple) or tickers.empty:
            log.warning("Failed to fetch initial data")
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
                log.warning(
                    f"Preload failed for {sym}: {e}",
                )
                self.latest_data[sym] = {"price": "N/A", "volume": "N/A"}
                self.previous_prices[sym] = None
        return self.latest_data, self.previous_prices

    async def handle_message(self, msg: dict):
        # websocker: updates previous_prices and latest_data
        symbol = msg.get("id", None)
        price = msg.get("price", 0)
        volume = msg.get("dayVolume", 0)

        prev_price = self.latest_data.get(symbol, {}).get("price")
        self.previous_prices[symbol] = prev_price
        self.latest_data[symbol] = {"price": price, "volume": volume}

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
                    log.debug(f"Retry succeeded for {sym}: {price}")
                except Exception as e:
                    log.warning(f"Retry {attempt+1}/{retries}failed for {sym}: {e}")
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
