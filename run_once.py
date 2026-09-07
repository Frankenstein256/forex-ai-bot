"""
run_once.py
-----------
This is the entry point for GitHub Actions. Unlike main.py (which
loops forever on a server), this script:

1. Runs ONE scan across all pairs
2. Sends a Telegram alert if a new setup is found
3. Saves what it found to state.json (so the NEXT run, 15 minutes
   later, knows not to re-send the same signal)
4. Exits

GitHub Actions will call this on a schedule (see
.github/workflows/scan.yml), so "looping" happens by GitHub simply
running this script again every 15 minutes - no server needed, and
nothing to "sleep".
"""

import json
import os

from config import PAIRS, MIN_SCORE, MIN_RR
from data_feed import get_candles
from strategy import evaluate_setup
from telegram_bot import send_message

STATE_FILE = "state.json"


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def scan_pair(pair_config: dict, state: dict) -> bool:
    """Returns True if state was changed (a new signal was found)."""
    symbol = pair_config["symbol"]
    smt_symbol = pair_config["smt_symbol"]

    h4 = get_candles(symbol, "4h", output_size=50)
    m15 = get_candles(symbol, "15min", output_size=50)

    comparison_m15 = None
    if smt_symbol:
        comparison_m15 = get_candles(smt_symbol, "15min", output_size=50)

    latest_candle_time = m15[-1]["time"]

    setup = evaluate_setup(
        h4, m15, comparison_m15,
        MIN_SCORE, MIN_RR,
        comparison_label=smt_symbol or "none",
    )

    if setup is None:
        print(f"[{symbol}] [{latest_candle_time}] No setup.")
        return False

    if state.get(symbol) == latest_candle_time:
        print(f"[{symbol}] [{latest_candle_time}] Already alerted for this candle. Skipping.")
        return False

    state[symbol] = latest_candle_time

    message = (
        f"*New Signal - {symbol}*\n"
        f"Direction: {setup.direction.upper()}\n"
        f"Entry: {setup.entry:.5f}\n"
        f"Stop: {setup.stop:.5f}\n"
        f"Target: {setup.target:.5f}\n"
        f"RR: {setup.rr:.2f}\n"
        f"Score: {setup.score}\n"
        f"Reasons: {', '.join(setup.reasons)}\n\n"
        f"_This is a signal from an experimental bot, not financial advice. "
        f"Still being validated - trade responsibly._"
    )
    print(message)
    send_message(message)
    return True


def main():
    state = load_state()
    changed = False

    for pair_config in PAIRS:
        try:
            if scan_pair(pair_config, state):
                changed = True
        except Exception as e:
            print(f"Error scanning {pair_config['symbol']}: {e}")

    if changed:
        save_state(state)
        print("State updated.")
    else:
        print("No changes to state.")


if __name__ == "__main__":
    main()
