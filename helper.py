def to_frontend_symbol(sym: str) -> str:
    if sym in ["BTC-USD", "BTC-CAD"]:
        return "BTC-CAD"
    if sym in ["ETH-USD", "ETH-CAD"]:
        return "ETH-CAD"
    return sym


def to_backend_symbol(sym: str) -> str:
    if sym == "BTC/USDT" or sym == "BTC":
        return "BTC-CAD"
    if sym == "ETH/USDT" or sym == "ETH":
        return "ETH-CAD"
    if sym == "SHIB":
        return "SHIB-CAD"
    if sym == "SOL":
        return "SOL-CAD"
    if sym == "XLM":
        return "XLM-CAD"
    return sym
