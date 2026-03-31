import os
import logging
import json
import pyotp
from ws_api import WealthsimpleAPI
from ws_api.exceptions import OTPRequiredException, LoginFailedException
from typing import Dict, List
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s  [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)


class WealthSimpleManager:
    """Manages WealthSimple authentication and data extraction using ws-api (GraphQL)."""

    def __init__(self, email: str = "", password: str = "", totp_secret: str = ""):
        self.email = email or os.getenv("WS_EMAIL")
        self.password = password or os.getenv("WS_PASSWORD")
        self.totp_secret = totp_secret or os.getenv("WS_2FA_SECRET")
        self.ws = None
        print(self.email, self.password)
        self._validate()

    def _validate(self):
        if not self.email:
            raise ValueError("email not found")

        if not self.password:
            raise ValueError("password not found")

        if not self.totp_secret:
            raise ValueError("totp_secret not found")

    def get_otp_code(self) -> str:
        """Generates the current 6-digit TOTP code."""
        if not self.totp_secret:
            raise ValueError("WS_2FA_SECRET not found in .env")
        totp = pyotp.TOTP(self.totp_secret.replace(" ", ""))
        code = totp.now()
        log.debug("Generated 2FA code")
        return code

    def login(self):
        """Authenticates with WealthSimple using ws-api."""
        if not self.email or not self.password:
            raise ValueError("WS_EMAIL or WS_PASSWORD not found in .env")

        log.info("Attempting to login to WealthSimple for %s", self.email)
        try:
            # Generate OTP immediately
            otp = self.get_otp_code()
            log.info("Attempting login with generated OTP...")
            try:
                session = WealthsimpleAPI.login(
                    self.email, self.password, otp_answer=otp
                )
                log.debug("session created")

                self.ws = WealthsimpleAPI(session)
                log.info("Successfully logged in to WealthSimple.")
            except (OTPRequiredException, LoginFailedException) as e:
                # If it still fails, it might be because WealthSimple wants a fresh login first
                # or the OTP was rejected.
                log.warning(
                    "Login with immediate OTP failed, retrying without OTP to trigger a fresh challenge..."
                )
                try:
                    session = WealthsimpleAPI.login(self.email, self.password)
                    self.ws = WealthsimpleAPI(session)
                except OTPRequiredException:
                    otp = self.get_otp_code()
                    log.info("OTP required, retrying with new TOTP code...")
                    session = WealthsimpleAPI.login(
                        self.email, self.password, otp_answer=otp
                    )
                    self.ws = WealthsimpleAPI(session)
                    log.info("Successfully logged in to WealthSimple.")

        except Exception as e:
            log.error("Failed to login to WealthSimple: %s", e)
            raise

    def map_symbol(self, security_node: Dict) -> str:
        """Maps WealthSimple security node to yfinance-compatible symbols."""
        # The structure from ws-api GraphQL varies, we need to find the ticker and exchange
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

    def get_aggregated_portfolio(self) -> Dict[str, Dict]:
        """Fetches and aggregates all stocks, ETFs, and crypto from all accounts."""
        if not self.ws:
            self.login()

        log.info("Fetching identity positions...")
        # get_identity_positions(None, "CAD") returns all positions across all accounts
        try:
            positions_edges = self.ws.get_identity_positions(None, "CAD")
        except Exception as e:
            log.error("Failed to fetch positions: %s", e)
            return {}

        # Dictionary to store aggregated data: {symbol: {'shares': float, 'total_book_value': float}}
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


def get_wealthsimple_portfolio(manager: WealthSimpleManager) -> Dict[str, Dict]:
    """Helper function to be called from main.py."""

    manager.login()
    # return

    all_account_info = manager.ws.get_accounts(open_only=True)
    self_traded_account_ids = [
        acc["id"]
        for acc in all_account_info
        if "SELF_DIRECTED" in acc["unifiedAccountType"]
    ]

    unique_security_book_price = defaultdict(lambda: {"shares": 0.0, "book_value": 0.0})

    for account_id in self_traded_account_ids:
        securities_info = manager.ws.get_account_balances(account_id)
        for security_id, _ in securities_info.items():
            if security_id not in ["sec-c-cad", "sec-c-usd"]:  # remove currency
                security_id = security_id.replace("[", "").replace("]", "")

                get_all_info_on_security = manager.ws.get_identity_positions(
                    security_ids=security_id, currency="CAD"
                )

                for data in get_all_info_on_security:
                    security_type = data.get("security").get("securityType")
                    if security_type not in [
                        "EQUITY",
                        "CRYPTOCURRENCY",
                        "EXCHANGE_TRADED_FUND",
                    ]:
                        # Skip anything but stocks and actual securities
                        continue

                        # print(
                        #     f"id: {data.get("security").get("id")}, data: \n{data.get("security")}"
                        # )

                    security_name = (
                        data.get("security").get("stock").get("symbol", security_id)
                    )
                    security_account_id = data.get("accounts")[0].get("id")

                    if account_id == security_account_id:
                        unique_security_book_price[security_name]["shares"] += float(
                            data.get("quantity")
                        )
                        unique_security_book_price[security_name][
                            "book_value"
                        ] += float(data.get("bookValue").get("amount"))

    # print(f"unique_security_book_price: {unique_security_book_price}")
    return unique_security_book_price


from collections import defaultdict

from wealthsimple_integration import get_wealthsimple_portfolio, WealthSimpleManager
import yaml
from yaml.representer import Representer, SafeRepresenter

yaml.add_representer(defaultdict, Representer.represent_dict)
yaml.representer.SafeRepresenter.add_representer(
    defaultdict, SafeRepresenter.represent_dict
)
if __name__ == "__main__":
    # Test script
    logging.basicConfig(level=logging.INFO)
    import yaml

    try:
        manager = WealthSimpleManager()
        portfolio = get_wealthsimple_portfolio(manager)
        with open("SYMBOLS.yaml", "w") as file:
            yaml.dump(portfolio, file, default_flow_style=False, sort_keys=False)

        # portfolio = test()

        print(json.dumps(portfolio, indent=2))
    except Exception as e:
        log.error("Test execution failed: %s", e)
