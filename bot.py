import os
import threading
from flask import Flask
import time
import requests
import pandas as pd
import numpy as np

# ==============================================================================
# 0. FLASK KEEP-ALIVE SERVER (FOR RENDER)
# ==============================================================================
app = Flask(__name__)

@app.route('/')
def home():
    return "AI Trading Bot is Live & Scanning 24/7!"

# ==============================================================================
# 1. CONFIGURATION
# ==============================================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY")

# Assets to scan daily for signals
SYMBOLS = ["XAU/USD", "EUR/USD", "GBP/USD", "USD/JPY"]

# AI Gatekeeper Settings
MIN_AI_CONFIDENCE = 75.0  # Only send signals with 75%+ confidence

# Cooldown to avoid duplicate alerts (1 hour per symbol)
COOLDOWN_PERIOD = 3600
last_alert_time = {}

# ==============================================================================
# 2. TELEGRAM DISPATCH
# ==============================================================================
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error sending Telegram alert: {e}")

# ==============================================================================
# 3. AI SCORING ENGINE
# ==============================================================================
def calculate_ai_confidence(df, signal_type):
    score = 50.0  # Base neutral score
    latest = df.iloc[-1]

    # 1. EMA Trend Alignment
    if signal_type == "BUY" and latest['close'] > latest['ema_20']:
        score += 15.0
    elif signal_type == "SELL" and latest['close'] < latest['ema_20']:
        score += 15.0

    # 2. RSI Momentum
    if signal_type == "BUY" and latest['rsi'] > 50:
        score += 15.0
    elif signal_type == "SELL" and latest['rsi'] < 50:
        score += 15.0

    # 3. Volatility Expansion (ATR)
    if latest['atr'] > df['atr'].mean():
        score += 10.0

    return min(score, 95.0)

# ==============================================================================
# 4. MARKET SCANNER
# ==============================================================================
def analyze_market(symbol):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=1h&outputsize=100&apikey={TWELVE_DATA_API_KEY}"
    res = requests.get(url).json()

    if "values" not in res:
        return

    df = pd.DataFrame(res['values'])
    df['close'] = df['close'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df = df.iloc[::-1].reset_index(drop=True)

    # Technical Indicators
    df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()

    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # ATR (14)
    df['tr'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift()),
            abs(df['low'] - df['close'].shift())
        )
    )
    df['atr'] = df['tr'].rolling(14).mean()

    latest = df.iloc[-1]
    current_price = latest['close']
    atr = latest['atr']

    signal = None

    if latest['close'] > latest['ema_20'] and latest['ema_20'] > latest['ema_50']:
        signal = "BUY"
    elif latest['close'] < latest['ema_20'] and latest['ema_50'] > latest['ema_20']:
        signal = "SELL"

    if signal:
        confidence = calculate_ai_confidence(df, signal)

        if confidence >= MIN_AI_CONFIDENCE:
            current_time = time.time()
            if symbol in last_alert_time and (current_time - last_alert_time[symbol]) < COOLDOWN_PERIOD:
                return

            tp = current_price + (atr * 2) if signal == "BUY" else current_price - (atr * 2)
            sl = current_price - (atr * 1.5) if signal == "BUY" else current_price + (atr * 1.5)

            msg = (
                f"🚨 *AI TRADING SIGNAL* 🚨\n\n"
                f"Asset: *{symbol}*\n"
                f"Action: *{signal}*\n"
                f"Entry: `{current_price:.2f}`\n"
                f"TP: `{tp:.2f}`\n"
                f"SL: `{sl:.2f}`\n"
                f"Confidence: *{confidence:.1f}%*"
            )

            send_telegram(msg)
            last_alert_time[symbol] = current_time

# ==============================================================================
# 5. MAIN SCANNER LOOP
# ==============================================================================
def run_trading_bot():
    print("🚀 Public AI Engine Started... Scanning Market...")
    send_telegram("✅ Bot is live and scanning 24/7 for signals.")
    while True:
        try:
            for symbol in SYMBOLS:
                analyze_market(symbol)
                time.sleep(2)  # Respect API limits
        except Exception as e:
            print(f"Error in main loop: {e}")

        time.sleep(60)  # Scan interval

# ==============================================================================
# 6. APPLICATION ENTRY POINT
# ==============================================================================
# Start the market scanner loop on a background thread.
# This runs the moment the module is imported, so it works whether the app
# is launched via `python bot.py` OR via gunicorn (gunicorn bot:app), which
# never executes the __main__ block below.
threading.Thread(target=run_trading_bot, daemon=True).start()

if __name__ == "__main__":
    # Start the Flask web server (only used for local/dev runs — Render uses gunicorn)
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
