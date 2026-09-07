"""
main.py
-------
This is the file Render actually runs.

Render's free "Web Service" tier expects something to be listening
on a web port (that's how Render checks the service is alive). Our
bot doesn't actually need to serve a website - it just scans the
market quietly in the background. So we run a TINY fake webpage
(just says "Bot is running") on one thread, purely to keep Render
happy, while the real scanning loop runs on another thread.

The scanning loop itself does:
1. For each configured pair (EURUSD, XAUUSD, USDJPY):
   - Fetch fresh candle data
   - Check for a valid setup
   - If found (and it's a NEW setup, not one we already sent), alert Telegram
2. Wait, then repeat
"""

import os
import time
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer

from config import PAIRS, MIN_SCORE, MIN_RR, SCAN_SECONDS, check_config
from data_feed import get_candles
from strategy import evaluate_setup
from telegram_bot import send_message

# Keeps track of the last candle time we already sent a signal for,
# PER SYMBOL, so we don't spam the same signal every scan loop and
# so pairs don't overwrite each other's tracking.
last_signal_time = {}


# ---------- Tiny fake webpage, just to satisfy Render's port check ----------

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/backtest"):
            self.handle_backtest()
            return

        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Signal bot is running. Visit /backtest to run a historical test.")

    def handle_backtest(self):
        # Imported here (not at the top) so a backtest crash can't
        # accidentally break the always-on scanning bot on startup.
        from backtest import run_full_backtest

        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Running backtest... this can take a minute or two. Please wait, don't refresh.\n\n")
        self.wfile.flush()

        try:
            _, report = run_full_backtest()
            self.wfile.write(report.encode("utf-8"))
        except Exception as e:
            self.wfile.write(f"Backtest failed: {e}".encode("utf-8"))

    def log_message(self, format, *args):
        pass  # keeps Render logs clean - we don't need every web ping logged


def run_fake_webserver():
    port = int(os.environ.get("PORT", 10000))  # Render sets PORT automatically
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"Fake webserver listening on port {port} (for Render's benefit only)")
    server.serve_forever()


# ---------- The actual bot logic ----------

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


def run_scan_loop():
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


def main():
    # Run the scan loop in a background thread...
    scanner_thread = threading.Thread(target=run_scan_loop, daemon=True)
    scanner_thread.start()

    # ...while the main thread just keeps a webpage alive for Render.
    run_fake_webserver()


if __name__ == "__main__":
    main()
