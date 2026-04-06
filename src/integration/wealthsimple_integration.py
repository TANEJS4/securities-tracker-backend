import logging
import pyotp
from src.ws_api import WealthsimpleAPI


from src.ws_api.exceptions import OTPRequiredException, LoginFailedException
from typing import Dict
from collections import defaultdict
from src.utils.logger import logger
from src.config.settings import settings


class WealthSimpleManager:

    def __init__(self):
        self.email = settings.ws_email
        self.password = settings.ws_password
        self.totp_secret = settings.ws_totp_secret

        self.ws = None
        logger.info(f"WS object initialized with user: {self.email} ")

    def get_otp_code(self) -> str:
        if not self.totp_secret:
            raise ValueError("WS_2FA_SECRET not found in .env")
        totp = pyotp.TOTP(self.totp_secret.get_secret_value().replace(" ", ""))
        code = totp.now()
        logger.info("Generated 2FA code")
        return code

    def login(self):
        if not self.email or not self.password:
            raise ValueError("WS_EMAIL or WS_PASSWORD not found in .env")

        logger.info("Attempting to login to WealthSimple for %s", self.email)
        try:
            # generate OTP
            otp = self.get_otp_code()
            logger.info("Attempting login with generated OTP...")
            try:
                session = WealthsimpleAPI.login(
                    self.email, self.password, otp_answer=otp
                )
                logger.info("session created")

                self.ws = WealthsimpleAPI(session)
                logger.info("Successfully logged in to WealthSimple.")
            except (OTPRequiredException, LoginFailedException) as e:
                # if this  still fails, it might be because WealthSimple wants a fresh login first or the OTP was rejected.
                logger.warning(
                    "Login with immediate OTP failed, retrying without OTP to trigger a fresh challenge..."
                )
                try:
                    session = WealthsimpleAPI.login(self.email, self.password)
                    self.ws = WealthsimpleAPI(session)
                except OTPRequiredException:
                    otp = self.get_otp_code()
                    logger.info("OTP required, retrying with new TOTP code...")
                    session = WealthsimpleAPI.login(
                        self.email, self.password, otp_answer=otp
                    )
                    self.ws = WealthsimpleAPI(session)
                    logger.info("Successfully logged in to WealthSimple.")

        except Exception as e:
            logger.error("Failed to login to WealthSimple: %s", e)
            raise

    #! Deprecated
    def map_symbol(self, security_node: Dict) -> str | None:
        # ws-api GraphQL API
        stock = security_node.get("stock", {})
        symbol = stock.get("symbol") or security_node.get("symbol")
        exchange = (
            stock.get("primaryExchange") or security_node.get("primaryExchange") or ""
        )
        asset_type = (stock.get("type") or security_node.get("type") or "").lower()

        if not symbol:
            return None

        # Handle class-based symbols (e.g., CTC.A -> CTC-A)
        if "." in symbol:
            symbol = symbol.replace(".", "-")

        if asset_type == "crypto" or "crypto" in exchange.lower():
            # Defaulting to -CAD as per user requirement
            return f"{symbol}-CAD"

        if exchange == "TSX":
            return f"{symbol}.TO"
        elif exchange == "TSX-V":
            return f"{symbol}.V"
        elif exchange == "NEO" or "NEO" in exchange:
            return f"{symbol}.NE"

        return symbol

    #! Deprecated
    def get_aggregated_portfolio(self) -> Dict[str, Dict]:
        if not self.ws:
            self.login()

        logger.info("Fetching identity positions...")
        # get_identity_positions(None, "CAD") returns all positions across all accounts
        try:
            positions_edges = self.ws.get_identity_positions(None, "CAD")
        except Exception as e:
            logger.error("Failed to fetch positions: %s", e)
            return {}

        #  {symbol: {'shares': float, 'total_book_value': float}}
        aggregated = {}

        for edge in positions_edges:
            # The edge usually contains 'node' which has 'security' and 'quantity'
            node = edge.get("node", edge)  # Handle different response structures if any
            security = node.get("security", {})

            # Extract account type to filter
            account = node.get("account", {})
            account_type = account.get("type", "").lower()

            if "managed" in account_type:
                continue

            symbol = self.map_symbol(security)
            if not symbol:
                continue

            shares = float(node.get("quantity", 0))
            # 'bookValue' in GraphQL response is typically a Money object
            book_value_node = node.get("bookValue", {})
            total_book_value = float(book_value_node.get("amount", 0))

            if symbol in aggregated:
                aggregated[symbol]["shares"] += shares
                aggregated[symbol]["total_book_value"] += total_book_value
            else:
                aggregated[symbol] = {
                    "shares": shares,
                    "total_book_value": total_book_value,
                }

        final_symbols = {}
        for symbol, data in aggregated.items():
            shares = data["shares"]
            if shares > 0:
                avg_book_price = round(data["total_book_value"] / shares, 4)
                final_symbols[symbol] = {"book_value": avg_book_price, "shares": shares}

        return final_symbols


def format_security_yfinance_friendly(
    symbol: str, security_type: str, security_exchange=None
):
    if security_type == "CRYPTOCURRENCY" and security_exchange is None:
        symbol += "-CAD"
    if (
        security_exchange
        and security_exchange == "TSX"
        and security_type
        in [
            "EQUITY",
            "EXCHANGE_TRADED_FUND",
        ]
    ):
        symbol = symbol.replace(".", "-")
        symbol += ".TO"
    return symbol


from forex_python.converter import CurrencyRates

_cached_forex_rate_usd_cad = 0.0


def get_usd_to_cad_rate():
    global _cached_forex_rate_usd_cad
    try:
        c = CurrencyRates()
        _cached_forex_rate_usd_cad = float(c.get_rate("USD", "CAD"))

        # result = c.convert("USD", "CAD", price)
        logging.info(f"USD TO CAD {_cached_forex_rate_usd_cad}")
        result = _cached_forex_rate_usd_cad

    except:
        logging.error(
            "Exchange rate could not be fetched, attempting to use cached rate"
        )
        if _cached_forex_rate_usd_cad != 0.0:
            result = _cached_forex_rate_usd_cad
        else:
            logging.error(
                "Exchange rate could not be fetched, cached rate is 0.0, falling back to USD"
            )
            result = None

    return result


def covert_usd_to_cad(value: float, security_type: str, security_exchange=None):
    if (
        security_exchange
        and security_exchange != "TSX"
        and security_type
        in [
            "EQUITY",
            "EXCHANGE_TRADED_FUND",
        ]
    ):
        value = value * _cached_forex_rate_usd_cad
    return value


def get_wealthsimple_portfolio(manager: WealthSimpleManager) -> Dict[str, Dict]:
    manager.login()
    all_account_info = manager.ws.get_accounts(open_only=True)
    # SKIP managed accounts as we cant sell or update security
    self_traded_account_ids = [
        acc["id"]
        for acc in all_account_info
        if "SELF_DIRECTED" in acc["unifiedAccountType"]
    ]

    # EX: unique_security_book_price = {"NVDA": {"shares" : 12.1, "book_value":1234.0}}
    unique_security_book_price = defaultdict(lambda: {"shares": 0.0, "book_value": 0.0})
    # startup call to cache exchange rate
    get_usd_to_cad_rate()

    for account_id in self_traded_account_ids:
        securities_info = manager.ws.get_account_balances(account_id)

        for security_id, _ in securities_info.items():
            # remove cash reserve (you can add it later)
            if security_id not in ["sec-c-cad", "sec-c-usd"]:
                security_id = security_id.replace("[", "").replace("]", "")

                get_all_info_on_security = manager.ws.get_identity_positions(
                    security_ids=security_id, currency="CAD"
                )

                for data in get_all_info_on_security:
                    security_type = data.get("security").get("securityType")
                    if security_type in [
                        "EQUITY",
                        "CRYPTOCURRENCY",
                        "EXCHANGE_TRADED_FUND",
                    ]:
                        # Skip anything but  actual securities - skips MONEY and precious metal

                        security_exchange = (
                            data.get("security").get("stock").get("primaryExchange")
                        )

                        security_name = format_security_yfinance_friendly(
                            symbol=data.get("security")
                            .get("stock")
                            .get("symbol", security_id),
                            security_type=security_type,
                            security_exchange=security_exchange,
                        )

                        # print(
                        #     f"security_name: {security_name}, Data: \n {data}\n\n............."
                        # )
                        security_account_id = data.get("accounts")[0].get("id")

                        if account_id == security_account_id:
                            unique_security_book_price[security_name][
                                "shares"
                            ] += float(data.get("quantity"))
                            book_value_cad = covert_usd_to_cad(
                                float(data.get("bookValue").get("amount")),
                                security_type=security_type,
                                security_exchange=security_exchange,
                            )
                            unique_security_book_price[security_name][
                                "book_value"
                            ] += book_value_cad

    # print(f"unique_security_book_price: {unique_security_book_price}")
    return unique_security_book_price


# # Test
# if __name__ == "__main__":
#     from collections import defaultdict

#     from integration.wealthsimple_integration import (
#         get_wealthsimple_portfolio,
#         WealthSimpleManager,
#     )
#     import yaml
#     from yaml.representer import Representer, SafeRepresenter

#     yaml.add_representer(defaultdict, Representer.represent_dict)
#     yaml.representer.SafeRepresenter.add_representer(
#         defaultdict, SafeRepresenter.represent_dict
#     )
#     # Test script
#     logging.basicConfig(level=logging.INFO)
#     import yaml

#     try:
#         manager = WealthSimpleManager()
#         portfolio = get_wealthsimple_portfolio(manager)
#         with open("SYMBOLS.yaml", "w") as file:
#             yaml.dump(portfolio, file, default_flow_style=False, sort_keys=False)

#         # portfolio = test()

#         print(json.dumps(portfolio, indent=2))
#     except Exception as e:
#         logger.error("Test execution failed: %s", e)
