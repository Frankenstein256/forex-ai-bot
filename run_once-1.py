"""
run_once.py
-----------
Entry point for GitHub Actions. Runs ONE scan cycle across all pairs:

1. For each pair: fetch data (using cached H4 where valid), trim to
   the last CONFIRMED closed candle, and check for a setup.
2. Before looking for a NEW setup on a symbol, first resolve any
   PENDING (previously-failed-to-deliver) signal for that symbol -
   either retry it, or drop it as stale.
3. Record what happened (API status, setup found, Telegram status)
   to a lightweight health log.
4. Persist state.json (dedup), pending_signals.json (retry queue),
   and h4_cache.json back to disk so GitHub Actions can commit them.

Nothing here modifies strategy.py - the strategy logic itself is out
of scope for this phase.
"""

import json
import os
from datetime import datetime, timezone

from config import (
    PAIRS, MIN_SCORE, MIN_RR,
    SCAN_INTERVAL_MINUTES,
    TWELVEDATA_DAILY_CREDIT_LIMIT, TWELVEDATA_PER_MINUTE_CREDIT_LIMIT,
    TELEGRAM_MAX_RETRIES, TELEGRAM_STALE_MINUTES, PENDING_SIGNALS_FILE,
    SCAN_HEALTH_FILE, SCAN_HEALTH_MAX_LINES,
)
from data_feed import get_candles, trim_to_closed, parse_utc
from strategy import evaluate_setup
from telegram_bot import try_send_message
from errors import RateLimitError, MalformedDataError, APIError
import cache_store

STATE_FILE = "state.json"

M15_INTERVAL_MINUTES = 15
H4_INTERVAL_MINUTES = 240


# ---------- State / pending / health file I/O ----------

def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def append_health_record(record: dict):
    lines = []
    if os.path.exists(SCAN_HEALTH_FILE):
        with open(SCAN_HEALTH_FILE, "r") as f:
            lines = f.readlines()
    lines.append(json.dumps(record) + "\n")
    if len(lines) > SCAN_HEALTH_MAX_LINES:
        lines = lines[-SCAN_HEALTH_MAX_LINES:]
    with open(SCAN_HEALTH_FILE, "w") as f:
        f.writelines(lines)


# ---------- Credit usage estimate (informational, not enforced) ----------

def estimate_daily_credits():
    """
    Estimates roughly how many TwelveData credits/day this configuration
    uses, given SCAN_INTERVAL_MINUTES and the current PAIRS list. This is
    an ESTIMATE for your visibility, not a hard limiter - actual usage
    can vary (e.g. retries on failure use extra credits).
    """
    runs_per_day = (24 * 60) // SCAN_INTERVAL_MINUTES

    m15_calls_per_run = 0
    for pair in PAIRS:
        m15_calls_per_run += 1  # primary M15
        if pair["smt_symbol"]:
            m15_calls_per_run += 1  # comparison M15

    m15_calls_per_day = m15_calls_per_run * runs_per_day

    # H4 candles close 6x/day (24h / 4h) regardless of scan frequency,
    # and we need one H4 series per pair (for HTF bias).
    h4_refreshes_per_day = 6
    h4_calls_per_day = h4_refreshes_per_day * len(PAIRS)

    total = m15_calls_per_day + h4_calls_per_day
    return {
        "runs_per_day": runs_per_day,
        "m15_calls_per_day": m15_calls_per_day,
        "h4_calls_per_day": h4_calls_per_day,
        "estimated_total_per_day": total,
    }


def log_credit_estimate():
    est = estimate_daily_credits()
    total = est["estimated_total_per_day"]
    limit = TWELVEDATA_DAILY_CREDIT_LIMIT
    pct = (total / limit * 100) if limit else 0

    print(f"Estimated TwelveData usage: ~{total} credits/day "
          f"(configured daily limit: {limit}, ~{pct:.0f}% of it)")
    print(f"  - assumes {est['runs_per_day']} runs/day at {SCAN_INTERVAL_MINUTES}-min intervals "
          f"(keep SCAN_INTERVAL_MINUTES in sync with the cron schedule in scan.yml)")
    print(f"  - M15 calls/day: {est['m15_calls_per_day']}, H4 calls/day (cached): {est['h4_calls_per_day']}")

    if limit and total > limit * 0.8:
        print(f"  WARNING: estimated usage is over 80% of your configured daily limit. "
              f"Consider raising SCAN_INTERVAL_MINUTES or reducing pairs/SMT comparisons.")


# ---------- Message formatting (shared by fresh + retried signals) ----------

def build_signal_message(signal: dict) -> str:
    return (
        f"*New Signal - {signal['symbol']}*\n"
        f"Direction: {signal['direction'].upper()}\n"
        f"Entry: {signal['entry']:.5f}\n"
        f"Stop: {signal['stop']:.5f}\n"
        f"Target: {signal['target']:.5f}\n"
        f"RR: {signal['rr']:.2f}\n"
        f"Score: {signal['score']}\n"
        f"Reasons: {', '.join(signal['reasons'])}\n\n"
        f"_This is a signal from an experimental bot, not financial advice. "
        f"Still being validated - trade responsibly._"
    )


def setup_to_signal_dict(symbol: str, candle_time: str, setup) -> dict:
    return {
        "symbol": symbol,
        "candle_time": candle_time,
        "direction": setup.direction,
        "entry": setup.entry,
        "stop": setup.stop,
        "target": setup.target,
        "rr": setup.rr,
        "score": setup.score,
        "reasons": setup.reasons,
    }


# ---------- Staleness check for pending (undelivered) signals ----------

def check_stale(pending_entry: dict, current_closed_time: str,
                 h4, m15, comparison_m15) -> tuple:
    """
    Returns (is_stale: bool, reason: str or None).

    A pending signal is considered stale if EITHER:
    1. Too much time has passed since the signal's candle (configurable
       via TELEGRAM_STALE_MINUTES), OR
    2. Re-evaluating the strategy on the CURRENT closed candle no longer
       produces a matching setup (same direction) - meaning the
       opportunity itself has likely already moved on.
    """
    signal_time = parse_utc(pending_entry["candle_time"])
    now_candle_time = parse_utc(current_closed_time)
    age_minutes = (now_candle_time - signal_time).total_seconds() / 60

    if age_minutes > TELEGRAM_STALE_MINUTES:
        return True, "time_expired"

    fresh_setup = evaluate_setup(
        h4, m15, comparison_m15, MIN_SCORE, MIN_RR,
        comparison_label=pending_entry.get("smt_label", "none"),
    )
    if fresh_setup is None or fresh_setup.direction != pending_entry["direction"]:
        return True, "setup_invalidated"

    return False, None


# ---------- Per-pair data fetch (with H4 caching) ----------

def fetch_pair_data(pair_config: dict, h4_cache: dict, now_utc: datetime):
    """
    Returns (h4, m15, comparison_m15, current_closed_time) for a pair,
    using cached H4 data when valid. Raises RateLimitError,
    MalformedDataError, or APIError on failure - callers must handle.
    """
    symbol = pair_config["symbol"]
    smt_symbol = pair_config["smt_symbol"]

    # --- M15 (never cached - always fetch fresh) ---
    m15_raw = get_candles(symbol, "15min", output_size=50)
    m15 = trim_to_closed(m15_raw, M15_INTERVAL_MINUTES, now_utc)
    if not m15:
        raise MalformedDataError(f"No confirmed-closed M15 candle available yet for {symbol}")
    current_closed_time = m15[-1]["time"]

    # --- H4 (cached - only refetch if cache is stale) ---
    if cache_store.is_cache_valid(h4_cache, symbol, now_utc):
        h4 = cache_store.get_cached_candles(h4_cache, symbol)
    else:
        h4_raw = get_candles(symbol, "4h", output_size=50)
        h4 = trim_to_closed(h4_raw, H4_INTERVAL_MINUTES, now_utc)
        if h4:
            cache_store.update_cache(h4_cache, symbol, h4, h4[-1]["time"], now_utc)

    # --- SMT comparison M15 (never cached) ---
    comparison_m15 = None
    if smt_symbol:
        comp_raw = get_candles(smt_symbol, "15min", output_size=50)
        comparison_m15 = trim_to_closed(comp_raw, M15_INTERVAL_MINUTES, now_utc)

    return h4, m15, comparison_m15, current_closed_time


# ---------- Main per-pair processing ----------

def process_pair(pair_config: dict, state: dict, pending: dict,
                  h4_cache: dict, now_utc: datetime) -> dict:
    symbol = pair_config["symbol"]
    smt_symbol = pair_config["smt_symbol"]

    health = {
        "scan_time": now_utc.strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": symbol,
        "candle_time": None,
        "api_status": "ok",
        "setup_found": False,
        "telegram_status": "not_applicable",
    }

    try:
        h4, m15, comparison_m15, current_closed_time = fetch_pair_data(pair_config, h4_cache, now_utc)
        health["candle_time"] = current_closed_time
    except RateLimitError as e:
        health["api_status"] = "rate_limited"
        health["error"] = str(e)
        print(f"[{symbol}] RATE LIMITED: {e}")
        return health
    except MalformedDataError as e:
        health["api_status"] = "malformed"
        health["error"] = str(e)
        print(f"[{symbol}] MALFORMED DATA: {e}")
        return health
    except APIError as e:
        health["api_status"] = "error"
        health["error"] = str(e)
        print(f"[{symbol}] API ERROR: {e}")
        return health

    # --- Resolve any pending (previously undelivered) signal first ---
    if symbol in pending:
        entry = pending[symbol]
        try:
            stale, reason = check_stale(entry, current_closed_time, h4, m15, comparison_m15)
        except Exception as e:
            # A strategy exception while re-validating a pending signal
            # should not crash the run - treat conservatively as stale.
            stale, reason = True, f"strategy_exception:{e}"
            print(f"[{symbol}] Strategy exception re-validating pending signal: {e}")

        if stale:
            print(f"[{symbol}] Pending signal dropped as stale ({reason}).")
            health["telegram_status"] = f"stale_dropped:{reason}"
            del pending[symbol]
        else:
            delivered = try_send_message(build_signal_message(entry))
            if delivered:
                print(f"[{symbol}] Pending signal delivered on retry.")
                health["telegram_status"] = "delivered_retry"
                del pending[symbol]
            else:
                entry["attempts"] += 1
                if entry["attempts"] >= TELEGRAM_MAX_RETRIES:
                    print(f"[{symbol}] Pending signal permanently failed after {entry['attempts']} attempts.")
                    health["telegram_status"] = "failed_permanent"
                    del pending[symbol]
                else:
                    print(f"[{symbol}] Pending signal retry failed (attempt {entry['attempts']}).")
                    health["telegram_status"] = "retry_pending"

    # --- Look for a NEW setup only if no pending signal remains for this symbol ---
    if symbol not in pending:
        try:
            setup = evaluate_setup(
                h4, m15, comparison_m15, MIN_SCORE, MIN_RR,
                comparison_label=smt_symbol or "none",
            )
        except Exception as e:
            health["strategy_status"] = "error"
            health["error"] = str(e)
            print(f"[{symbol}] STRATEGY EXCEPTION: {e}")
            return health

        if setup is not None:
            health["setup_found"] = True

            if state.get(symbol) == current_closed_time:
                print(f"[{symbol}] [{current_closed_time}] Setup already processed for this candle. Skipping.")
            else:
                state[symbol] = current_closed_time
                signal = setup_to_signal_dict(symbol, current_closed_time, setup)
                signal["smt_label"] = smt_symbol or "none"
                signal["attempts"] = 1

                delivered = try_send_message(build_signal_message(signal))
                if delivered:
                    print(f"[{symbol}] Signal delivered.")
                    health["telegram_status"] = "delivered"
                else:
                    print(f"[{symbol}] Signal delivery failed - queued for retry.")
                    health["telegram_status"] = "queued_for_retry"
                    pending[symbol] = signal
        else:
            print(f"[{symbol}] [{current_closed_time}] No setup.")

    return health


def main():
    now_utc = datetime.now(timezone.utc)

    log_credit_estimate()

    state = load_json(STATE_FILE, {})
    pending = load_json(PENDING_SIGNALS_FILE, {})
    h4_cache = cache_store.load_cache()

    state_before = json.dumps(state, sort_keys=True)
    pending_before = json.dumps(pending, sort_keys=True)
    cache_before = json.dumps(h4_cache, sort_keys=True)

    for pair_config in PAIRS:
        health = process_pair(pair_config, state, pending, h4_cache, now_utc)
        append_health_record(health)

    if json.dumps(state, sort_keys=True) != state_before:
        save_json(STATE_FILE, state)
        print("state.json updated.")

    if json.dumps(pending, sort_keys=True) != pending_before:
        save_json(PENDING_SIGNALS_FILE, pending)
        print("pending_signals.json updated.")

    if json.dumps(h4_cache, sort_keys=True) != cache_before:
        cache_store.save_cache(h4_cache)
        print("h4_cache.json updated.")


if __name__ == "__main__":
    main()
