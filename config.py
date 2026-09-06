"""
config.py
---------
This file just reads your settings from environment variables
(the ones you already set up in Render's dashboard).

Nothing here needs to be edited by hand - if you ever want to
change a setting, change it in Render's Environment tab, not here.
"""

import os

# --- Secrets (already in your Render env vars) ---
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# --- Market settings ---
SYMBOL = os.getenv("SYMBOL", "EUR/USD")
SMT_SYMBOL = os.getenv("SMT_SYMBOL", "GBP/USD")

# --- All pairs the bot scans ---
# Each entry is (symbol, smt_comparison_symbol_or_None).
# If smt_symbol is None, that pair just skips the SMT confluence check
# and scores on the other confluences instead.
PAIRS = [
    {"symbol": SYMBOL, "smt_symbol": SMT_SYMBOL},   # EUR/USD vs GBP/USD
    {"symbol": "XAU/USD", "smt_symbol": None},       # Gold - no free-tier SMT partner (Silver needs paid plan)
    {"symbol": "USD/JPY", "smt_symbol": None},       # no SMT partner configured yet
]

# --- Strategy settings ---
MIN_RR = float(os.getenv("MIN_RR", "2.0"))
MIN_SCORE = int(os.getenv("MIN_SCORE", "6"))

# --- Timing ---
SCAN_SECONDS = int(os.getenv("SCAN_SECONDS", "60"))

# --- Sanity check on startup ---
def check_config():
    missing = []
    if not TWELVEDATA_API_KEY:
        missing.append("TWELVEDATA_API_KEY")
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Set these in your Render dashboard under Environment."
        )
        
