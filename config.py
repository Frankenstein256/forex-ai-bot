"""
config.py
---------
This file reads your settings from environment variables.
"""

import os

# --- Secrets (already in your Render / GitHub env vars) ---
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# --- Market settings ---
SYMBOL = os.getenv("SYMBOL", "EUR/USD")
SMT_SYMBOL = os.getenv("SMT_SYMBOL", "GBP/USD")

# --- All pairs the bot scans ---
PAIRS = [
    {"symbol": "EUR/USD", "smt_symbol": "GBP/USD", "min_score": None},
    {"symbol": "GBP/USD", "smt_symbol": "EUR/USD", "min_score": None},
    {"symbol": "XAU/USD", "smt_symbol": None, "min_score": 4},
    {"symbol": "WTI/USD", "smt_symbol": None, "min_score": 4},
]

# --- Market hours guard ---
ENFORCE_MARKET_HOURS = os.getenv("ENFORCE_MARKET_HOURS", "true").lower() == "true"
FRIDAY_CLOSE_HOUR_UTC = int(os.getenv("FRIDAY_CLOSE_HOUR_UTC", "21"))
SUNDAY_OPEN_HOUR_UTC = int(os.getenv("SUNDAY_OPEN_HOUR_UTC", "22"))

# --- Trading session window ---
ENFORCE_SESSION_WINDOW = os.getenv("ENFORCE_SESSION_WINDOW", "true").lower() == "true"
LONDON_SESSION_START_UTC = int(os.getenv("LONDON_SESSION_START_UTC", "7"))
LONDON_SESSION_END_UTC = int(os.getenv("LONDON_SESSION_END_UTC", "10"))
NY_SESSION_START_UTC = int(os.getenv("NY_SESSION_START_UTC", "12"))
NY_SESSION_END_UTC = int(os.getenv("NY_SESSION_END_UTC", "15"))

# --- Strategy settings ---
RR_MULTIPLE = float(os.getenv("RR_MULTIPLE", "3.0"))
MIN_RR = float(os.getenv("MIN_RR", "2.0"))
MIN_SCORE = int(os.getenv("MIN_SCORE", "5"))

# --- Timing ---
SCAN_SECONDS = int(os.getenv("SCAN_SECONDS", "60"))
SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "15"))

# --- Twelve Data plan limits ---
TWELVEDATA_DAILY_CREDIT_LIMIT = int(os.getenv("TWELVEDATA_DAILY_CREDIT_LIMIT", "800"))
TWELVEDATA_PER_MINUTE_CREDIT_LIMIT = int(os.getenv("TWELVEDATA_PER_MINUTE_CREDIT_LIMIT", "8"))

# --- API retry / rate-limit handling ---
API_MAX_RETRIES = int(os.getenv("API_MAX_RETRIES", "2"))
API_RETRY_BACKOFF_SECONDS = float(os.getenv("API_RETRY_BACKOFF_SECONDS", "2"))

# --- Closed-candle safety ---
CLOSED_CANDLE_BUFFER_SECONDS = int(os.getenv("CLOSED_CANDLE_BUFFER_SECONDS", "10"))

# --- H4 caching ---
H4_CACHE_FILE = os.getenv("H4_CACHE_FILE", "h4_cache.json")

# --- Telegram retry / stale-signal safety ---
TELEGRAM_MAX_RETRIES = int(os.getenv("TELEGRAM_MAX_RETRIES", "3"))
TELEGRAM_STALE_MINUTES = int(os.getenv("TELEGRAM_STALE_MINUTES", "20"))
PENDING_SIGNALS_FILE = os.getenv("PENDING_SIGNALS_FILE", "pending_signals.json")

# --- Scan health logging ---
SCAN_HEALTH_FILE = os.getenv("SCAN_HEALTH_FILE", "scan_health.jsonl")
SCAN_HEALTH_MAX_LINES = int(os.getenv("SCAN_HEALTH_MAX_LINES", "500"))

# --- Paper trade lifecycle tracking ---
PAPER_TRADES_FILE = os.getenv("PAPER_TRADES_FILE", "paper_trades.json")
TRADE_HISTORY_FILE = os.getenv("TRADE_HISTORY_FILE", "trade_history.jsonl")
TRADE_HISTORY_MAX_LINES = int(os.getenv("TRADE_HISTORY_MAX_LINES", "1000"))

# --- Risk / account-protection circuit breaker ---
ENFORCE_RISK_GUARD = os.getenv("ENFORCE_RISK_GUARD", "false").lower() == "true"
DAILY_MAX_LOSSES = int(os.getenv("DAILY_MAX_LOSSES", "1"))
WEEKLY_MAX_LOSSES = int(os.getenv("WEEKLY_MAX_LOSSES", "2"))
WEEKLY_MAX_SIGNALS = int(os.getenv("WEEKLY_MAX_SIGNALS", "3"))

# --- Sanity check on startup ---
def check_config():
    missing = []
    if not TWELVEDATA_API_KEY:
        missing.append("TWELVEDATA_API_KEY")
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Set these as repository secrets or Render environment variables."
)
