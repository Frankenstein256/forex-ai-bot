import os
import threading
from flask import Flask
import time
import datetime
import requests
import pandas as pd
import numpy as np

# ==============================================================================
# 0. FLASK KEEP-ALIVE SERVER (FOR RENDER)
# ==============================================================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Top-Down SMC + Tori Trendline Bot is Live & Scanning!"

# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY")

SYMBOLS = ["XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY", "USD/CAD", "AUD/USD", "NZD/USD", "GBP/JPY"]

# How often (seconds) each timeframe is allowed to refresh from the API.
# Tuned to match each timeframe's actual candle-close cadence — no point
# re-fetching a 4H candle every 5 minutes. Keeps 8 symbols well under
# TwelveData's free-tier 800 calls/day limit (~650/day at these settings).
REFRESH = {"1day": 8 * 3600, "4h": 4 * 3600, "15min": 20 * 60}

cache = {s: {} for s in SYMBOLS}

# Cooldown per exact setup (zone or trendline level) so the same level
# doesn't spam repeatedly — but no cap on how many *different* setups fire.
SETUP_COOLDOWN_SECONDS = 90 * 60  # 1.5 hours
last_setup_signaled = {}  # key -> last signal time

# ==============================================================================
# 2. TELEGRAM DISPATCH
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
# 3. DATA FETCHING (CACHED PER TIMEFRAME, KEEPS TIMESTAMPS FOR TRENDLINES)
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
    df["ts"] = df["datetime"].astype("int64") // 10**9  # epoch seconds, for trendline regression
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
# 4. DAILY BIAS (TOP OF THE TOP-DOWN)
# ==============================================================================
def get_daily_bias(df):
    df = df.copy()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean() if len(df) >= 200 else df["ema50"]
    latest = df.iloc[-1]
    if latest["close"] > latest["ema50"] and latest["ema50"] >= latest.get("ema200", latest["ema50"]):
        return "bullish"
    elif latest["close"] < latest["ema50"] and latest["ema50"] <= latest.get("ema200", latest["ema50"]):
        return "bearish"
    return "neutral"

# ==============================================================================
# 5. 4H SUPPLY/DEMAND ZONE DETECTION
# ==============================================================================
def find_zones(df, bias, lookback=50, swing_window=2):
    df = df.tail(lookback).reset_index(drop=True)
    best_zone = None
    best_move = 0

    for i in range(swing_window, len(df) - swing_window):
        window = df.iloc[i - swing_window:i + swing_window + 1]
        pivot = df.iloc[i]

        if bias == "bullish":
            if pivot["low"] == window["low"].min():
                move_up = df["high"].iloc[i:i + swing_window + 3].max() - pivot["low"]
                if move_up > best_move:
                    best_move = move_up
                    best_zone = {"type": "demand", "top": pivot["high"], "bottom": pivot["low"]}

        elif bias == "bearish":
            if pivot["high"] == window["high"].max():
                move_down = pivot["high"] - df["low"].iloc[i:i + swing_window + 3].min()
                if move_down > best_move:
                    best_move = move_down
                    best_zone = {"type": "supply", "top": pivot["high"], "bottom": pivot["low"]}

    return best_zone

# ==============================================================================
# 6. TORI-STYLE TRENDLINE DETECTION (ACTION LINE)
# ==============================================================================
def find_trendline(df, bias, lookback=70, swing_window=2):
    """
    Fits an ascending support line (bullish) through recent swing lows,
    or a descending resistance line (bearish) through recent swing highs.
    Returns slope/intercept in terms of epoch-seconds so it can be evaluated
    at any timestamp, including on the M15 chart later.
    """
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

    # An ascending support line must actually slope up; descending resistance must slope down.
    if bias == "bullish" and slope <= 0:
        return None
    if bias == "bearish" and slope >= 0:
        return None

    return {"slope": slope, "intercept": intercept, "touches": len(recent)}

def trendline_value_at(trendline, ts):
    return trendline["slope"] * ts + trendline["intercept"]

# ==============================================================================
# 7. M15 ENTRY CONFIRMATION (ZONE REJECTION OR TRENDLINE BOUNCE)
# ==============================================================================
def check_zone_entry(df, zone):
    if zone is None or len(df) < 3:
        return False
    latest, prev = df.iloc[-1], df.iloc[-2]
    price_in_zone = latest["low"] <= zone["top"] and latest["high"] >= zone["bottom"]
    if not price_in_zone:
        return False
    if zone["type"] == "demand":
        return (latest["close"] > latest["open"] and latest["close"] > prev["open"]
                and latest["open"] <= prev["close"])
    return (latest["close"] < latest["open"] and latest["close"] < prev["open"]
            and latest["open"] >= prev["close"])

def check_trendline_bounce(df, trendline, bias):
    if trendline is None or len(df) < 3:
        return False
    latest, prev = df.iloc[-1], df.iloc[-2]
    line_now = trendline_value_at(trendline, latest["ts"])
    candle_range = max(latest["high"] - latest["low"], latest["close"] * 0.0005)
    touched_line = latest["low"] <= line_now <= latest["high"]

    if not touched_line:
        return False

    if bias == "bullish":
        # price dipped into the support line and closed back above it, green candle
        return latest["close"] > latest["open"] and latest["close"] > line_now
    else:
        # price poked into the resistance line and closed back below it, red candle
        return latest["close"] < latest["open"] and latest["close"] < line_now

# ==============================================================================
# 8. SIGNAL DISPATCH (SHARED BY BOTH SETUP TYPES)
# ==============================================================================
def fire_signal(symbol, bias, setup_label, level_desc, direction, entry_price, stop_loss, setup_key):
    now = time.time()
    if setup_key in last_setup_signaled and (now - last_setup_signaled[setup_key]) < SETUP_COOLDOWN_SECONDS:
        return

    risk = abs(entry_price - stop_loss)
    take_profit = entry_price + risk * 2 if direction == "BUY" else entry_price - risk * 2

    msg = (
        f"📊 *TOP-DOWN SIGNAL* 📊\n\n"
        f"Asset: *{symbol}*\n"
        f"Bias (Daily): *{bias.upper()}*\n"
        f"Setup: *{setup_label}*\n"
        f"Level: {level_desc}\n"
        f"Action: *{direction}*\n\n"
        f"Entry: `{entry_price:.4f}`\n"
        f"SL: `{stop_loss:.4f}`\n"
        f"TP: `{take_profit:.4f}` (1:2 RR)"
    )
    send_telegram(msg)
    last_setup_signaled[setup_key] = now

# ==============================================================================
# 10. MARKET SCANNER (TOP-DOWN: DAILY -> 4H -> M15, TWO SETUP TYPES)
# ==============================================================================
def analyze_market(symbol):
    df_daily = get_data(symbol, "1day")
    if df_daily is None:
        return
    bias = get_daily_bias(df_daily)
    if bias == "neutral":
        return

    df_4h = get_data(symbol, "4h")
    if df_4h is None:
        return
    df_m15 = get_data(symbol, "15min")
    if df_m15 is None:
        return

    latest_m15 = df_m15.iloc[-1]
    entry_price = latest_m15["close"]

    # --- Setup 1: Supply/Demand zone rejection ---
    zone = find_zones(df_4h, bias)
    if zone and check_zone_entry(df_m15, zone):
        stop_loss = zone["bottom"] * 0.999 if zone["type"] == "demand" else zone["top"] * 1.001
        direction = "BUY" if zone["type"] == "demand" else "SELL"
        setup_key = (symbol, "zone", round((zone["top"] + zone["bottom"]) / 2, 4))
        fire_signal(symbol, bias, "Supply/Demand Zone Rejection",
                    f"{zone['bottom']:.4f} - {zone['top']:.4f}", direction,
                    entry_price, stop_loss, setup_key)

    # --- Setup 2: Tori-style trendline bounce ---
    trendline = find_trendline(df_4h, bias)
    if trendline and check_trendline_bounce(df_m15, trendline, bias):
        line_now = trendline_value_at(trendline, latest_m15["ts"])
        # Safety line: a small buffer beyond the trendline for the stop
        buffer = entry_price * 0.0015
        stop_loss = line_now - buffer if bias == "bullish" else line_now + buffer
        direction = "BUY" if bias == "bullish" else "SELL"
        setup_key = (symbol, "trendline", round(line_now, 4))
        fire_signal(symbol, bias, "Tori Trendline Bounce",
                    f"Action Line @ {line_now:.4f}", direction,
                    entry_price, stop_loss, setup_key)

# ==============================================================================
# 11. MAIN SCANNER LOOP
# ==============================================================================
def is_weekend():
    return datetime.datetime.utcnow().weekday() >= 5  # 5=Sat, 6=Sun

def run_trading_bot():
    print("🚀 Top-Down SMC + Tori Trendline Engine Started...")
    send_telegram("✅ Bot is live: Daily bias -> 4H zones/trendlines -> M15 confirmation. Fires whenever a real setup appears.")
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

        time.sleep(300)  # scan every 5 minutes

# ==============================================================================
# 12. APPLICATION ENTRY POINT
# ==============================================================================
threading.Thread(target=run_trading_bot, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
    
