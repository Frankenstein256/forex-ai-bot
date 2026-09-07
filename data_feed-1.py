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

CHANGES IN THIS VERSION (Phase 1 reliability fixes):
1. Every request explicitly asks TwelveData for UTC timestamps, so our
   closed-candle math below is never thrown off by exchange-local time.
2. Requests retry on network errors / rate limits / malformed data,
   with a short backoff between attempts, instead of failing on the
   first hiccup.
3. Closed-candle detection is done with real timestamp math (see
   get_last_closed_index / trim_to_closed) instead of trusting that
   TwelveData's last returned row is always a finished candle.
"""

import time
import requests
from datetime import datetime, timedelta, timezone

from config import (
    TWELVEDATA_API_KEY,
    API_MAX_RETRIES,
    API_RETRY_BACKOFF_SECONDS,
    CLOSED_CANDLE_BUFFER_SECONDS,
)
from errors import APIError, RateLimitError, MalformedDataError

BASE_URL = "https://api.twelvedata.com/time_series"


def parse_utc(time_str: str) -> datetime:
    """
    Parses a TwelveData timestamp string as UTC. We explicitly request
    timezone=UTC on every call (see get_candles), so this assumption
    is safe - it is NOT guessing the timezone, it's relying on what we
    told TwelveData to give us.
    """
    dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=timezone.utc)


def get_candles(symbol: str, interval: str, output_size: int = 100):
    """
    Fetches candles from TwelveData, with retries on failure.

    Raises:
        RateLimitError    - TwelveData reported we're being rate limited
        MalformedDataError - response was empty/unparseable
        APIError          - any other request failure
    """
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": output_size,
        "apikey": TWELVEDATA_API_KEY,
        "format": "JSON",
        "timezone": "UTC",  # critical for correct closed-candle math
    }

    last_error = None

    for attempt in range(API_MAX_RETRIES + 1):
        try:
            response = requests.get(BASE_URL, params=params, timeout=15)
        except requests.RequestException as e:
            last_error = APIError(f"Network error fetching {symbol} {interval}: {e}")
            time.sleep(API_RETRY_BACKOFF_SECONDS * (attempt + 1))
            continue

        if response.status_code == 429:
            last_error = RateLimitError(f"Rate limited fetching {symbol} {interval} (HTTP 429)")
            time.sleep(API_RETRY_BACKOFF_SECONDS * (attempt + 1))
            continue

        try:
            data = response.json()
        except ValueError:
            last_error = MalformedDataError(f"Non-JSON response for {symbol} {interval}")
            time.sleep(API_RETRY_BACKOFF_SECONDS * (attempt + 1))
            continue

        if isinstance(data, dict) and data.get("status") == "error":
            code = data.get("code")
            message = data.get("message", "")
            if code == 429 or "limit" in message.lower():
                last_error = RateLimitError(f"Rate limited fetching {symbol} {interval}: {message}")
            else:
                last_error = APIError(f"TwelveData error for {symbol} {interval}: {message}")
            time.sleep(API_RETRY_BACKOFF_SECONDS * (attempt + 1))
            continue

        if "values" not in data or not data["values"]:
            last_error = MalformedDataError(f"Empty/malformed data for {symbol} {interval}: {data}")
            time.sleep(API_RETRY_BACKOFF_SECONDS * (attempt + 1))
            continue

        try:
            candles = []
            for row in reversed(data["values"]):  # oldest first
                candles.append({
                    "time": row["datetime"],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                })
        except (KeyError, ValueError, TypeError) as e:
            last_error = MalformedDataError(f"Malformed candle row for {symbol} {interval}: {e}")
            time.sleep(API_RETRY_BACKOFF_SECONDS * (attempt + 1))
            continue

        return candles  # success

    raise last_error


def get_last_closed_index(candles, interval_minutes: int, now_utc: datetime = None,
                           buffer_seconds: int = None):
    """
    Walks backward through the candle list and returns the INDEX of the
    first candle that is provably closed: now_utc >= candle_open_time +
    interval_length + safety_buffer.

    This does NOT assume candles[-1] or candles[-2] is closed - it
    checks the actual timestamp math for each one. Returns None if no
    closed candle is found in the given list at all.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if buffer_seconds is None:
        buffer_seconds = CLOSED_CANDLE_BUFFER_SECONDS

    interval_length = timedelta(minutes=interval_minutes)
    buffer = timedelta(seconds=buffer_seconds)

    for i in range(len(candles) - 1, -1, -1):
        candle_open = parse_utc(candles[i]["time"])
        candle_close = candle_open + interval_length
        if now_utc >= candle_close + buffer:
            return i

    return None


def trim_to_closed(candles, interval_minutes: int, now_utc: datetime = None,
                    buffer_seconds: int = None):
    """
    Returns the candle list truncated so it ends at the last CONFIRMED
    closed candle. Anything after that (i.e. a still-forming candle)
    is dropped. Returns an empty list if no closed candle is available
    yet (e.g. right at market open with very little history).
    """
    idx = get_last_closed_index(candles, interval_minutes, now_utc, buffer_seconds)
    if idx is None:
        return []
    return candles[: idx + 1]
