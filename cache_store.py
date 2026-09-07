"""
cache_store.py
---------------
Handles caching of H4 candles.

WHY THIS IS SAFE:
An H4 candle only closes every 4 hours. Our scanner runs every ~15
minutes, so re-fetching H4 data on every single run means asking for
the same unchanged data roughly 16 times before it actually changes.
Caching it doesn't lose any accuracy - it just avoids wasted requests.

WHAT IS NOT CACHED:
M15 candles (for any symbol, including the SMT comparison pair) are
NEVER cached. A new M15 candle closes every run cycle, and the whole
point of the scanner is to react to the freshest one - caching that
would make the bot see stale entries. Only H4 (used purely for the
higher-timeframe bias) is cached.

HOW CACHE VALIDITY IS DECIDED:
Rather than a flat "refresh every 4 hours" timer (which can drift if a
run is delayed or skipped), we store the CLOSE timestamp of the last
closed H4 candle we fetched (open time + 4 hours). The cache stays
valid until the current time passes (that close timestamp + 4 hours) -
i.e. until a NEW H4 candle should provably have closed since the one
we cached. This self-corrects even if a run is late or missed entirely.
"""

import json
import os
from datetime import datetime, timedelta, timezone

from config import H4_CACHE_FILE
from data_feed import parse_utc

H4_INTERVAL = timedelta(hours=4)


def load_cache():
    if not os.path.exists(H4_CACHE_FILE):
        return {}
    with open(H4_CACHE_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_cache(cache):
    with open(H4_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def is_cache_valid(cache: dict, symbol: str, now_utc: datetime) -> bool:
    entry = cache.get(symbol)
    if not entry or "last_closed_close_time" not in entry or "candles" not in entry:
        return False
    last_closed_close_time = parse_utc(entry["last_closed_close_time"])
    return now_utc < last_closed_close_time + H4_INTERVAL


def get_cached_candles(cache: dict, symbol: str):
    entry = cache.get(symbol)
    if not entry:
        return None
    return entry.get("candles")


def update_cache(cache: dict, symbol: str, candles: list, last_closed_open_time: str,
                  now_utc: datetime):
    """
    last_closed_open_time: the "time" field of the last closed H4
    candle (its OPEN time, matching how candles are stored everywhere
    else in this codebase). We convert it to a CLOSE time internally
    since that's what actually determines when the cache should expire.
    """
    last_closed_close_time = parse_utc(last_closed_open_time) + H4_INTERVAL
    cache[symbol] = {
        "candles": candles,
        "last_closed_close_time": last_closed_close_time.strftime("%Y-%m-%d %H:%M:%S"),
        "cached_at": now_utc.strftime("%Y-%m-%d %H:%M:%S"),
    }
