import yaml

from src.utils.logger import logger


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

    logger.info(df[["time", "open", "high", "low", "close", "volume"]])
    return df[["time", "open", "high", "low", "close", "volume"]]


def read_symbol_yaml():
    try:
        with open("./SYMBOLS.yaml", "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.warning(f"Could not read SYMBOLS.yaml: {e}")
        return {}


SYMBOLS = read_symbol_yaml()
