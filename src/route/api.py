import asyncio
import logging

import yfinance as yf

from fastapi import APIRouter


from src.utils.logger import logger
from src.utils.transform import format_ohlcv, SYMBOLS
from src.route.helper import get_portfolio, get_positions, get_startup

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/portfolio")
def api_portfolio():

    return get_portfolio()


@router.get("/startup_portflio")
def startup_portflio():
    result = get_startup()
    logger.info(f"startup_portflio: {result}")
    return get_startup()


@router.get("/symbol_name")
async def api_symbol_name(symbol: str):
    def _fetch_name():
        try:
            info = yf.Ticker(symbol).info
            return info.get("longName") or info.get("shortName") or symbol
        except Exception:
            return symbol

    name = await asyncio.get_running_loop().run_in_executor(None, _fetch_name)
    logger.info(f"api_symbol_name: name: {symbol}: {name}")

    return {"name": f"{symbol}: {name}"}


@router.get("/positions")
def api_positions():
    result = get_positions()
    logger.info(f"result : {result} ")

    return result


@router.get("/chart/history")
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
        logger.info(f"api_chart_history: {records}")
        return records
    except Exception:
        logger.error(f"api_chart_history : {[]}")

        return []


# def get_positions() -> List[Dict]:
#     positions = []
#     for sym, info in SYMBOLS.items():
#         shares = info.get("shares")
#         book_price = info.get("book_value")
#         if shares is None or book_price is None:
#             continue

#         current_data = data_service.latest_data.get(sym, {})
#         current_price = current_data.get("price", 0.0)
#         if current_price == "N/A" or not isinstance(current_price, (int, float)):
#             current_price = 0.0

#         pl = round((current_price - book_price), 2)
#         performance = (
#             ((current_price - book_price) / book_price) * 100 if book_price else 0.0
#         )

#         positions.append(
#             {
#                 "symbol": sym,  # to_frontend_symbol(sym),
#                 "currentPrice": round(current_price, 2),
#                 "bookPrice": round((book_price), 2),
#                 "shares": shares,
#                 "pl": pl,
#             }
#         )
#     logger.info(f"get_positions: {positions}")

#     return positions


# def get_portfolio(previous_closes) -> Dict:
#     positions = get_positions()
#     logger.info(f"positions: {positions}")
#     logger.info(f"previous_closes: {previous_closes}")
#     total_value = sum(p["currentPrice"] * p["shares"] for p in positions)

#     daily_change = 0.0
#     for p in positions:
#         backend_sym = to_backend_symbol(p["symbol"])
#         backend_sym = p.get("symbol")
#         # prev_close = config.previous_closes.get(backend_sym, p["bookPrice"])
#         prev_close = previous_closes.get(backend_sym, p["bookPrice"])
#         daily_change += (p["currentPrice"] - prev_close) * p["shares"]

#     prev_total_value = total_value - daily_change
#     daily_change_percent = (
#         (daily_change / prev_total_value) * 100 if prev_total_value else 0.0
#     )
#     logger.info(
#         f"""get_portfolio :
#         "totalValue": {total_value},
#         "dailyChange": {daily_change},
#         "dailyChangePercent": {daily_change_percent}"""
#     )

#     return {
#         "totalValue": total_value,
#         "dailyChange": daily_change,
#         "dailyChangePercent": daily_change_percent,
#         # "goalPercentage": 65.0,
#     }


# def get_startup() -> float:
#     value = 0
#     for _, info in SYMBOLS.items():
#         book_price = info.get("book_value")
#         value += book_price
#     logger.info(f"get_startup: {value}")

#     return value
