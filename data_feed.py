"""
data_feed.py
------------
Talks to TwelveData's API and gets candle (price) data.

A "candle" here is just a dict like:
{
    "time": "2026-09-06 12:00:00",
    "open": 1.0921,
    "high": 1.0935,
    "low": 1.0915,
    "close": 1.0930
}

We fetch candles for three timeframes:
- H4 (4-hour) -> used for higher-timeframe bias
- M15 (15-minute) -> used for entries
- (GBP/USD M15 too, for SMT comparison)
"""

import requests
from config import TWELVEDATA_API_KEY

BASE_URL = "https://api.twelvedata.com/time_series"


def get_candles(symbol: str, interval: str, output_size: int = 100):
    """
    Fetches candles from TwelveData.

    symbol: e.g. "EUR/USD"
    interval: e.g. "15min", "1h", "4h"
    output_size: how many candles to fetch (most recent first from API,
                 we reverse it so oldest is first - easier to reason about)
    """
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": output_size,
        "apikey": TWELVEDATA_API_KEY,
        "format": "JSON",
    }

    response = requests.get(BASE_URL, params=params, timeout=15)
    data = response.json()

    if "values" not in data:
        # TwelveData returns an error message in "message" or "status"
        raise RuntimeError(f"TwelveData error for {symbol} {interval}: {data}")

    candles = []
    for row in reversed(data["values"]):  # oldest first
        candles.append({
            "time": row["datetime"],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        })

    return candles


def get_last_closed_candle(candles):
    """
    IMPORTANT: we only ever act on the most recently CLOSED candle,
    never the one that's still forming. TwelveData's most recent
    candle in the list can sometimes still be "live" depending on
    timing, so we always use the second-to-last one to be safe.
    """
    if len(candles) < 2:
        raise RuntimeError("Not enough candles returned to find a closed one.")
    return candles[-2]
