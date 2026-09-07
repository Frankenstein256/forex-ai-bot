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

# --- How often GitHub Actions actually runs this scanner (minutes) ---
# IMPORTANT: this must be kept in sync by hand with the cron schedule
# in .github/workflows/scan.yml. It's used only to ESTIMATE credit
# usage for you to review each run - it does not control the schedule
# itself (GitHub Actions' cron does that).
SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "15"))

# --- Twelve Data plan limits (CONFIGURABLE, not hard assumptions) ---
# These defaults reflect TwelveData's commonly published FREE plan
# limits as of when this was written: 800 credits/day, 8 credits/min.
# If your actual plan is different (paid tier, changed limits, etc.),
# override these via environment variables so credit estimates and
# any future throttling logic stay accurate for YOUR plan - nothing
# in the code assumes these numbers are fixed.
TWELVEDATA_DAILY_CREDIT_LIMIT = int(os.getenv("TWELVEDATA_DAILY_CREDIT_LIMIT", "800"))
TWELVEDATA_PER_MINUTE_CREDIT_LIMIT = int(os.getenv("TWELVEDATA_PER_MINUTE_CREDIT_LIMIT", "8"))

# --- API retry / rate-limit handling ---
API_MAX_RETRIES = int(os.getenv("API_MAX_RETRIES", "2"))
API_RETRY_BACKOFF_SECONDS = float(os.getenv("API_RETRY_BACKOFF_SECONDS", "2"))

# --- Closed-candle safety ---
# A candle is only treated as "closed" once (now >= candle_open_time +
# interval_length + this buffer). The buffer exists because a data
# provider can sometimes finalize a bar a few seconds late.
CLOSED_CANDLE_BUFFER_SECONDS = int(os.getenv("CLOSED_CANDLE_BUFFER_SECONDS", "10"))

# --- H4 caching ---
# H4 candles only change every 4 hours, so we cache them instead of
# re-fetching every 15-minute run. The cache is considered valid until
# a NEW H4 candle should have closed since it was last refreshed - see
# cache_store.py for the exact logic.
H4_CACHE_FILE = os.getenv("H4_CACHE_FILE", "h4_cache.json")

# --- Telegram retry / stale-signal safety ---
TELEGRAM_MAX_RETRIES = int(os.getenv("TELEGRAM_MAX_RETRIES", "3"))
# A pending (undelivered) signal older than this many minutes is
# considered stale and will NOT be sent late - it gets dropped and
# logged instead. Default of 20 min is roughly "one M15 candle cycle
# plus a bit of slack" - tune this if your tolerance for lateness differs.
TELEGRAM_STALE_MINUTES = int(os.getenv("TELEGRAM_STALE_MINUTES", "20"))
PENDING_SIGNALS_FILE = os.getenv("PENDING_SIGNALS_FILE", "pending_signals.json")

# --- Scan health logging ---
SCAN_HEALTH_FILE = os.getenv("SCAN_HEALTH_FILE", "scan_health.jsonl")
# Caps the health log so it doesn't grow forever - oldest lines are
# dropped once this many are exceeded.
SCAN_HEALTH_MAX_LINES = int(os.getenv("SCAN_HEALTH_MAX_LINES", "500"))

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
            "Set these as GitHub Actions repository secrets."
        )
