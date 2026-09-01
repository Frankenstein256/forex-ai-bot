import os
import threading
from flask import Flask
import time
import datetime
import requests
import pandas as pd
import numpy as np
from collections import defaultdict

# ==============================================================================
# 0. FLASK KEEP-ALIVE SERVER (FOR RENDER DEPLOYMENT)
# ==============================================================================
app = Flask(__name__)

SIGNAL_LOG_PATH = "/tmp/signal_log.csv"

@app.route('/')
def home():
    return "Multi-Asset Strategy Engine (XAU, EUR, GBP, JPY) is Live & Scanning!"

@app.route('/log')
def view_log():
    try:
        with open(SIGNAL_LOG_PATH) as f:
            return f"<pre>{f.read()}</pre>"
    except FileNotFoundError:
        return "No signals logged yet this session."

# ==============================================================================
# 1. CONFIGURATION & CORE ASSET MATRIX
# ==============================================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY")

# Primary 4-Asset Focus: Gold + Top 3 Forex Pairs
SYMBOLS = ["XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY"]

# Candle refresh limits to preserve API quotas
REFRESH = {"1day": 8 * 3600, "4h": 4 * 3600, "15min": 20 * 60, "1week": 24 * 3600}

cache = defaultdict(dict)

SETUP_COOLDOWN_SECONDS = 90 * 60  # 1.5-hour cooldown per setup
last_setup_signaled = {}

NEWS_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
NEWS_REFRESH_SECONDS = 6 * 3600
NEWS_BUFFER_MINUTES = 30
news_cache = {"data": None, "ts": 0}

# ==============================================================================
# 2. TELEGRAM ALERTS
# ==============================================================================
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload)
        print(f"Telegram response: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Error sending Telegram alert: {e}")

# ==============================================================================
# 3. DATA FETCHING & CACHING
# ==============================================================================
def fetch_candles(symbol, interval, outputsize=150):
    url = (f"https://api.twelvedata.com/time_series?symbol={symbol}"
           f"&interval={interval}&outputsize={outputsize}&apikey={TWELVE_DATA_API_KEY}")
    res = requests.get(url).json()
    if "values" not in res:
        print(f"No data for {symbol} {interval}: {res}")
        return None
    df = pd.DataFrame(res["values"])
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].astype(float)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["ts"] = df["datetime"].astype("int64") // 10**9
    df = df.iloc[::-1].reset_index(drop=True)
    return df

def get_data(symbol, interval):
    now = time.time()
    entry = cache[symbol].get(interval)
    if entry and (now - entry["ts"]) < REFRESH[interval]:
        return entry["df"]
    df = fetch_candles(symbol, interval)
    if df is not None:
        cache[symbol][interval] = {"df": df, "ts": now}
        return df
    return entry["df"] if entry else None

# ==============================================================================
# 4. EMA TREND & BIAS STRATEGY (50 EMA & 200 EMA)
# ==============================================================================
def get_trend_bias(df):
    df = df.copy()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean() if len(df) >= 200 else df["ema50"]
    latest = df.iloc[-1]
    
    # Bullish: Price > 50 EMA and 50 EMA >= 200 EMA
    if latest["close"] > latest["ema50"] and latest["ema50"] >= latest.get("ema200", latest["ema50"]):
        return "bullish"
    # Bearish: Price < 50 EMA and 50 EMA <= 200 EMA
    elif latest["close"] < latest["ema50"] and latest["ema50"] <= latest.get("ema200", latest["ema50"]):
        return "bearish"
    return "neutral"

def get_daily_bias_only(symbol):
    df_daily = get_data(symbol, "1day")
    if df_daily is None:
        return None
    bias = get_trend_bias(df_daily)
    return bias if bias != "neutral" else None

# ==============================================================================
# 5. RSI CONFIRMATION & SESSION TIMING
# ==============================================================================
def in_session(symbol):
    hour = datetime.datetime.utcnow().hour
    if "JPY" in symbol:
        return not (21 <= hour < 23)
    return 7 <= hour < 21

def calculate_rsi(df, period=14):
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def rsi_confirms(df, direction):
    rsi = calculate_rsi(df)
    if rsi.empty or pd.isna(rsi.iloc[-1]):
        return False, None
    latest_rsi = rsi.iloc[-1]
    # RSI Momentum rules: 45-80 for BUY (Bullish Zone), 20-55 for SELL (Bearish Zone)
    ok = (45 <= latest_rsi <= 80) if direction == "BUY" else (20 <= latest_rsi <= 55)
    return ok, latest_rsi

# ==============================================================================
# 6. CONFLUENCE SCORING ENGINE
# ==============================================================================
MIN_CONFLUENCE_SCORE = 50

def compute_confluence_score(symbol, bias, direction, df_m15):
    score = 0
    details = []

    # 1. Higher-Timeframe Weekly Alignment (EMA)
    df_weekly = get_data(symbol, "1week")
    if df_weekly is not None and get_trend_bias(df_weekly) == bias:
        score += 20
        details.append("Weekly EMA Trend Aligned (+20)")

    # 2. ICT Liquidity Sweep / Stop Hunt Reclaim
    if check_liquidity_sweep(df_m15, bias):
        score += 25
        details.append("M15 Liquidity Sweep Confirmed (+25)")

    # 3. DXY USD Correlation
    if dxy_confirms(symbol, direction):
        score += 15
        details.append("DXY Correlation Aligned (+15)")

    # 4. RSI 14 Momentum Zone
    rsi_ok, rsi_val = rsi_confirms(df_m15, direction)
    if rsi_ok:
        score += 15
        details.append(f"RSI 14 Momentum Aligned ({rsi_val:.0f}) (+15)")

    # 5. Active Session Liquidity Window
    if in_session(symbol):
        score += 15
        details.append("Active Session Liquidity (+15)")

    return score, details

# ==============================================================================
# 7. HIGH-IMPACT NEWS FILTER
# ==============================================================================
def get_news_calendar():
    now = time.time()
    if news_cache["data"] and (now - news_cache["ts"]) < NEWS_REFRESH_SECONDS:
        return news_cache["data"]
    try:
        res = requests.get(NEWS_URL, timeout=10).json()
        news_cache["data"] = res
        news_cache["ts"] = now
        return res
    except Exception as e:
        print(f"News calendar fetch failed: {e}")
        return news_cache["data"]

def is_near_high_impact_news(symbol):
    events = get_news_calendar()
    if not events:
        return False
    base, quote = symbol.split("/")
    currencies = {base, quote}
    now_ts = time.time()
    for ev in events:
        try:
            if ev.get("impact") != "High" or ev.get("country") not in currencies:
                continue
            event_ts = pd.to_datetime(ev["date"]).timestamp()
            if abs(now_ts - event_ts) <= NEWS_BUFFER_MINUTES * 60:
                return True
        except Exception:
            continue
    return False

# ==============================================================================
# 8. DXY CORRELATION CHECK
# ==============================================================================
def get_dxy_bias():
    df = get_data("DXY", "1day")
    if df is None:
        return None
    return get_trend_bias(df)

def dxy_confirms(symbol, direction):
    if "USD" not in symbol:
        return True
    dxy_bias = get_dxy_bias()
    if dxy_bias is None or dxy_bias == "neutral":
        return True
    base, quote = symbol.split("/")
    if quote == "USD":
        return dxy_bias == "bearish" if direction == "BUY" else dxy_bias == "bullish"
    if base == "USD":
        return dxy_bias == "bullish" if direction == "BUY" else dxy_bias == "bearish"
    return True

# ==============================================================================
# 9. 4H SMC SUPPLY & DEMAND ZONES
# ==============================================================================
def find_zones(df, bias, lookback=50, swing_window=2):
    df = df.tail(lookback).reset_index(drop=True)
    best_zone = None
    best_move = 0
    for i in range(swing_window, len(df) - swing_window):
        window = df.iloc[i - swing_window:i + swing_window + 1]
        pivot = df.iloc[i]
        if bias == "bullish" and pivot["low"] == window["low"].min():
            move_up = df["high"].iloc[i:i + swing_window + 3].max() - pivot["low"]
            if move_up > best_move:
                best_move = move_up
                best_zone = {"type": "demand", "top": pivot["high"], "bottom": pivot["low"]}
        elif bias == "bearish" and pivot["high"] == window["high"].max():
            move_down = pivot["high"] - df["low"].iloc[i:i + swing_window + 3].min()
            if move_down > best_move:
                best_move = move_down
                best_zone = {"type": "supply", "top": pivot["high"], "bottom": pivot["low"]}
    return best_zone

# ==============================================================================
# 10. TORI ACTION LINE (TRENDLINE) DETECTION
# ==============================================================================
def find_trendline(df, bias, lookback=70, swing_window=2):
    df = df.tail(lookback).reset_index(drop=True)
    pivots = []
    for i in range(swing_window, len(df) - swing_window):
        window = df.iloc[i - swing_window:i + swing_window + 1]
        pivot = df.iloc[i]
        if bias == "bullish" and pivot["low"] == window["low"].min():
            pivots.append((pivot["ts"], pivot["low"]))
        elif bias == "bearish" and pivot["high"] == window["high"].max():
            pivots.append((pivot["ts"], pivot["high"]))
    if len(pivots) < 2:
        return None
    recent = pivots[-3:] if len(pivots) >= 3 else pivots[-2:]
    xs = np.array([p[0] for p in recent], dtype=float)
    ys = np.array([p[1] for p in recent], dtype=float)
    slope, intercept = np.polyfit(xs, ys, 1)
    if bias == "bullish" and slope <= 0:
        return None
    if bias == "bearish" and slope >= 0:
        return None
    return {"slope": slope, "intercept": intercept}

def trendline_value_at(trendline, ts):
    return trendline["slope"] * ts + trendline["intercept"]

# ==============================================================================
# 11. ENTRY CONFIRMATION ENGINE
# ==============================================================================
def check_zone_entry(df, zone):
    if zone is None or len(df) < 3:
        return False
    latest, prev = df.iloc[-1], df.iloc[-2]
    if not (latest["low"] <= zone["top"] and latest["high"] >= zone["bottom"]):
        return False
    if zone["type"] == "demand":
        return (latest["close"] > latest["open"] and latest["close"] > prev["open"]
                and latest["open"] <= prev["close"])
    return (latest["close"] < latest["open"] and latest["close"] < prev["open"]
            and latest["open"] >= prev["close"])

def check_trendline_bounce(df, trendline, bias):
    if trendline is None or len(df) < 3:
        return False
    latest = df.iloc[-1]
    line_now = trendline_value_at(trendline, latest["ts"])
    if not (latest["low"] <= line_now <= latest["high"]):
        return False
    if bias == "bullish":
        return latest["close"] > latest["open"] and latest["close"] > line_now
    return latest["close"] < latest["open"] and latest["close"] < line_now

def check_liquidity_sweep(df, bias, lookback=8):
    if len(df) < lookback + 1:
        return False
    window = df.tail(lookback + 1).reset_index(drop=True)
    prior, latest = window.iloc[:-1], window.iloc[-1]
    if bias == "bullish":
        local_low = prior["low"].min()
        return latest["low"] < local_low and latest["close"] > local_low
    local_high = prior["high"].max()
    return latest["high"] > local_high and latest["close"] < local_high

# ==============================================================================
# 12. LOGGING & TELEGRAM SIGNAL DISPATCH
# ==============================================================================
def log_signal(symbol, bias, setup_label, direction, entry, sl, tp):
    try:
        file_exists = os.path.isfile(SIGNAL_LOG_PATH)
        with open(SIGNAL_LOG_PATH, "a") as f:
            if not file_exists:
                f.write("timestamp,symbol,bias,setup,direction,entry,sl,tp\n")
            f.write(f"{datetime.datetime.utcnow().isoformat()},{symbol},{bias},"
                    f"{setup_label},{direction},{entry},{sl},{tp}\n")
    except Exception as e:
        print(f"Failed to log signal: {e}")

def fire_signal(symbol, bias, setup_label, level_desc, direction, entry_price, stop_loss, setup_key, score, details):
    now = time.time()
    if setup_key in last_setup_signaled and (now - last_setup_signaled[setup_key]) < SETUP_COOLDOWN_SECONDS:
        return

    risk = abs(entry_price - stop_loss)
    take_profit = entry_price + risk * 2 if direction == "BUY" else entry_price - risk * 2
    details_text = "\n".join(f"✔ {d}" for d in details) if details else "(Structure Only)"

    msg = (
        f"📊 *STRATEGY SIGNAL* 📊\n\n"
        f"Asset: *{symbol}*\n"
        f"Daily EMA Bias: *{bias.upper()}*\n"
        f"Setup: *{setup_label}*\n"
        f"Level: {level_desc}\n"
        f"Action: *{direction}*\n\n"
        f"Entry: `{entry_price:.4f}`\n"
        f"SL: `{stop_loss:.4f}`\n"
        f"TP: `{take_profit:.4f}` (1:2 RR)\n\n"
        f"Confluence Score: *{score}/90*\n"
        f"{details_text}"
    )
    send_telegram(msg)
    log_signal(symbol, bias, setup_label, direction, entry_price, stop_loss, take_profit)
    last_setup_signaled[setup_key] = now

# ==============================================================================
# 13. MARKET SCANNER ENGINE
# ==============================================================================
def analyze_market(symbol):
    if is_near_high_impact_news(symbol):
        return

    bias = get_daily_bias_only(symbol)
    if bias is None:
        return

    df_4h = get_data(symbol, "4h")
    df_m15 = get_data(symbol, "15min")
    if df_4h is None or df_m15 is None:
        return

    latest_m15 = df_m15.iloc[-1]
    entry_price = latest_m15["close"]
    direction = "BUY" if bias == "bullish" else "SELL"

    # Setup 1: 4H Supply/Demand Zone Rejection
    zone = find_zones(df_4h, bias)
    if zone and check_zone_entry(df_m15, zone):
        score, details = compute_confluence_score(symbol, bias, direction, df_m15)
        if score >= MIN_CONFLUENCE_SCORE:
            stop_loss = zone["bottom"] * 0.999 if zone["type"] == "demand" else zone["top"] * 1.001
            setup_key = (symbol, "zone", round((zone["top"] + zone["bottom"]) / 2, 4))
            fire_signal(symbol, bias, "SMC Zone Rejection",
                        f"{zone['bottom']:.4f} - {zone['top']:.4f}", direction,
                        entry_price, stop_loss, setup_key, score, details)

    # Setup 2: Tori Action Line (Trendline) Bounce
    trendline = find_trendline(df_4h, bias)
    if trendline and check_trendline_bounce(df_m15, trendline, bias):
        score, details = compute_confluence_score(symbol, bias, direction, df_m15)
        if score >= MIN_CONFLUENCE_SCORE:
            line_now = trendline_value_at(trendline, latest_m15["ts"])
            buffer = entry_price * 0.0015
            stop_loss = line_now - buffer if bias == "bullish" else line_now + buffer
            setup_key = (symbol, "trendline", round(line_now, 4))
            fire_signal(symbol, bias, "Tori Action Line Bounce",
                        f"Action Line @ {line_now:.4f}", direction,
                        entry_price, stop_loss, setup_key, score, details)

# ==============================================================================
# 14. EXECUTION LOOP & ENTRY POINT
# ==============================================================================
def is_weekend():
    return datetime.datetime.utcnow().weekday() >= 5

def run_trading_bot():
    print("🚀 Multi-Asset Strategy Engine Active...")
    send_telegram(
        "✅ Engine updated: Active pairs set to XAU/USD, EUR/USD, GBP/USD, USD/JPY.\n"
        "Strategy integrated: Daily EMA (50/200) trend filter + 4H S/D & Action Lines + "
        "M15 execution with RSI momentum and news filter."
    )
    while True:
        try:
            if is_weekend():
                print("Market closed (weekend) — skipping scan.")
            else:
                for symbol in SYMBOLS:
                    analyze_market(symbol)
                    time.sleep(2)
        except Exception as e:
            print(f"Error in main loop: {e}")
        time.sleep(300)

threading.Thread(target=run_trading_bot, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
