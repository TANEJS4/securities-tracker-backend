import config
from typing import Dict, List

from helper import to_backend_symbol

from src.utils.logger import logger
from src.utils.transform import SYMBOLS


def get_positions() -> List[Dict]:
    positions = []
    for sym, info in SYMBOLS.items():
        shares = info.get("shares")
        book_price = info.get("book_value")
        if shares is None or book_price is None:
            continue

        current_price = getattr(config, "latest_data", {})
        logger.debug(f"current_price full: {current_price}")
        current_price = current_price.get(sym, 0.0)
        logger.debug(f"current_price sym: {current_price}")
        current_price = current_price.get("price", 0.0)
        logger.debug(f"current_price sym: {current_price}")

        if current_price == "N/A" or not isinstance(current_price, (int, float)):
            current_price = 0.0

        pl = round((current_price * shares) - book_price, 2)

        positions.append(
            {
                "symbol": sym,  # to_frontend_symbol(sym),
                "currentPrice": round(current_price, 2),
                "bookPrice": round((book_price), 2),
                "shares": shares,
                "pl": pl,
            }
        )
    logger.debug(f"get_positions: {positions}")

    return positions


def get_portfolio(previous_closes=None) -> Dict:
    if not previous_closes:
        logger.info(f"api_portfolio: {getattr(config, "previous_closes", {})}")
        previous_closes = getattr(config, "previous_closes", {})
    positions = get_positions()
    logger.debug(f"positions: {positions}")
    logger.debug(f"previous_closes: {previous_closes}")
    total_value = sum(p["currentPrice"] * p["shares"] for p in positions)

    daily_change = 0.0
    for p in positions:
        backend_sym = to_backend_symbol(p["symbol"])
        backend_sym = p.get("symbol")
        # prev_close = config.previous_closes.get(backend_sym, p["bookPrice"])
        prev_close = previous_closes.get(backend_sym, p["bookPrice"])
        daily_change += (p["currentPrice"] - prev_close) * p["shares"]

    prev_total_value = total_value - daily_change
    daily_change_percent = (
        (daily_change / prev_total_value) * 100 if prev_total_value else 0.0
    )
    logger.info(
        f"""get_portfolio : 
        "totalValue": {total_value},
        "dailyChange": {daily_change},
        "dailyChangePercent": {daily_change_percent}"""
    )

    return {
        "totalValue": total_value,
        "dailyChange": daily_change,
        "dailyChangePercent": daily_change_percent,
    }


def get_startup() -> float:
    value = 0
    for _, info in SYMBOLS.items():
        book_price = info.get("book_value")
        value += book_price
    logger.info(f"get_startup: {value}")

    return value
