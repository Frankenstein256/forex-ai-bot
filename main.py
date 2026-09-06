"""
main.py
-------
This is the file Render actually runs. It loops forever:
1. For each configured pair (EURUSD, XAUUSD, USDJPY):
   - Fetch fresh candle data
   - Check for a valid setup
   - If found (and it's a NEW setup, not one we already sent), alert Telegram
2. Wait, then repeat
"""

import time
import traceback

from config import PAIRS, MIN_SCORE, MIN_RR, SCAN_SECONDS, check_config
from data_feed import get_candles
from strategy import evaluate_setup
from telegram_bot import send_message

# Keeps track of the last candle time we already sent a signal for,
# PER SYMBOL, so we don't spam the same signal every scan loop and
# so pairs don't overwrite each other's tracking.
last_signal_time = {}


def scan_pair(pair_config: dict):
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
        print(f"[{symbol}] [{latest_candle_time}] No setup. Waiting...")
        return

    if last_signal_time.get(symbol) == latest_candle_time:
        print(f"[{symbol}] [{latest_candle_time}] Setup already alerted. Skipping duplicate.")
        return

    last_signal_time[symbol] = latest_candle_time

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


def main():
    check_config()
    pair_names = ", ".join(p["symbol"] for p in PAIRS)
    send_message(f"✅ Signal bot started. Scanning: {pair_names}")

    while True:
        for pair_config in PAIRS:
            try:
                scan_pair(pair_config)
            except Exception as e:
                print(f"Error scanning {pair_config['symbol']}:", e)
                traceback.print_exc()
        time.sleep(SCAN_SECONDS)


if __name__ == "__main__":
    main()
