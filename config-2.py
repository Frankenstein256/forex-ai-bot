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
# Each entry: symbol, smt_comparison_symbol_or_None, min_score_or_None.
# If smt_symbol is None, that pair skips the SMT confluence check and
# scores on the other confluences instead - which shrinks its maximum
# possible score (6 instead of 8), so min_score is calibrated down
# proportionally for those pairs to keep the same relative "how much
# real confluence is required" bar as pairs that DO have SMT. A
# min_score of None means "use the global MIN_SCORE default".
PAIRS = [
    {"symbol": SYMBOL, "smt_symbol": SMT_SYMBOL, "min_score": None},  # EUR/USD vs GBP/USD
    {"symbol": "XAU/USD", "smt_symbol": None, "min_score": 4},  # Gold - no free-tier SMT partner (Silver needs paid plan);
                                                                  # min_score=4 keeps ~same proportional bar as EURUSD's default 5-of-8 (5/8=62.5%; 4/6=~67%)
    {"symbol": "USD/JPY", "smt_symbol": "EUR/JPY", "min_score": None},  # EUR/JPY as a genuine correlated SMT partner
                                                                          # (unconfirmed on free TwelveData plan until first real run - watch scan_health.jsonl)
]

# --- Market hours guard ---
# Skips evaluation entirely on weekends (see market_hours.py) so the
# bot never generates signals off dead/stale weekend price data.
ENFORCE_MARKET_HOURS = os.getenv("ENFORCE_MARKET_HOURS", "true").lower() == "true"
FRIDAY_CLOSE_HOUR_UTC = int(os.getenv("FRIDAY_CLOSE_HOUR_UTC", "21"))
SUNDAY_OPEN_HOUR_UTC = int(os.getenv("SUNDAY_OPEN_HOUR_UTC", "22"))

# --- Strategy settings ---
MIN_RR = float(os.getenv("MIN_RR", "2.0"))
# MIN_SCORE: threshold out of a max of 8 (EUR/USD, which has an SMT
# partner) or 6 (XAU/USD, USD/JPY, which don't). Lowered from 6 to 5
# on [priority change: signal generation first] - at 6, pairs without
# an SMT partner were mathematically forced to require EVERY remaining
# condition (sweep AND FVG AND displacement, zero slack), which was
# too close to an all-or-nothing gate. At 5: EUR/USD needs any 2 of
# {sweep, SMT, FVG}; XAU/USD and USD/JPY need sweep+FVG together
# (displacement becomes optional rather than mandatory). Still
# requires genuine multi-factor confluence - not a single condition.
MIN_SCORE = int(os.getenv("MIN_SCORE", "5"))

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

# --- Phase 2: paper trade lifecycle tracking ---
PAPER_TRADES_FILE = os.getenv("PAPER_TRADES_FILE", "paper_trades.json")
TRADE_HISTORY_FILE = os.getenv("TRADE_HISTORY_FILE", "trade_history.jsonl")
# Caps the closed-trade history so it doesn't grow forever.
TRADE_HISTORY_MAX_LINES = int(os.getenv("TRADE_HISTORY_MAX_LINES", "1000"))

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
