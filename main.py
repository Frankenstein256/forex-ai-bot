"""
main.py
-------
GitHub Actions Execution Script.

This script scans your target pairs, detects setups via strategy.py,
runs an AI audit through ai_filter.py (Gemini 2.5 Flash), and dispatches
confirmed signals directly to Telegram.
"""

import time
import traceback

from config import PAIRS, check_config
from data_feed import get_candles
from strategy import evaluate_setup
from ai_filter import filter_setup_with_ai
from telegram_bot import send_message

# Tracks the last candle time a signal was sent per pair to avoid duplicates
last_signal_time = {}


def scan_pair(pair_config: dict):
    symbol = pair_config["symbol"]
    smt_symbol = pair_config["smt_symbol"]

    # 1. Fetch live candle data
    h4 = get_candles(symbol, "4h", output_size=50)
    m15 = get_candles(symbol, "15min", output_size=50)

    comparison_m15 = None
    if smt_symbol:
        comparison_m15 = get_candles(smt_symbol, "15min", output_size=50)

    latest_candle_time = m15[-1]["datetime"] if "datetime" in m15[-1] else m15[-1].get("time")

    # 2. Evaluate algorithmic strategy rules
    setup = evaluate_setup(
        symbol_h4=h4,
        symbol_m15=m15,
        comparison_m15=comparison_m15,
    )

    if setup is None:
        print(f"[{symbol}] [{latest_candle_time}] No setup detected or outside killzone.")
        return

    if last_signal_time.get(symbol) == latest_candle_time:
        print(f"[{symbol}] [{latest_candle_time}] Setup already alerted. Skipping duplicate.")
        return

    # 3. AI Filter Audit with Gemini
    print(f"[{symbol}] Algorithmic setup detected! Requesting AI audit from Gemini Flash...")
    try:
        ai_audit = filter_setup_with_ai(
            symbol=symbol,
            setup=setup,
            m15_recent_candles=m15,
            h4_recent_candles=h4
        )
    except Exception as e:
        print(f"[{symbol}] AI Audit Error: {e}")
        traceback.print_exc()
        return

    # 4. Gate execution behind AI Approval
    if ai_audit.approve_trade and ai_audit.confidence_score >= 70:
        last_signal_time[symbol] = latest_candle_time

        ai_confluences_formatted = "\n".join([f"• {c}" for c in ai_audit.ai_confluences])
        algo_reasons_formatted = ", ".join(setup.reasons)

        message = (
            f"🤖 *AI APPROVED SIGNAL ({ai_audit.confidence_score}% Confidence)*\n\n"
            f"**Symbol:** {symbol} | **Direction:** {setup.direction.upper()}\n"
            f"**Entry:** {setup.entry}\n"
            f"**Stop Loss:** {setup.stop}\n"
            f"**Take Profit:** {setup.target} (1:{setup.rr:.1f} R:R)\n\n"
            f"📌 *Algorithmic Setup:* {algo_reasons_formatted}\n\n"
            f"🧠 *AI Confluences:*\n{ai_confluences_formatted}\n\n"
            f"⚠️ *AI Risk Note:* {ai_audit.risk_notes}\n\n"
            f"_Trade responsibly._"
        )
        print(f"[{symbol}] AI Approved. Dispatching signal to Telegram...")
        send_message(message)
    else:
        print(
            f"[{symbol}] Setup REJECTED by Gemini AI. "
            f"Confidence: {ai_audit.confidence_score}%. Reason: {ai_audit.risk_notes}"
        )


def main():
    check_config()
    print("Checking markets...")

    for pair_config in PAIRS:
        try:
            scan_pair(pair_config)
        except Exception as e:
            print(f"Error scanning {pair_config['symbol']}: {e}")
            traceback.print_exc()


if __name__ == "__main__":
    main()
   
