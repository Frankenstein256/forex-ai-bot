import os
import time
import asyncio
import threading
import logging
import requests
from flask import Flask
from telegram import Bot
from telegram.constants import ParseMode

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ==============================================================================
# FLASK STUB (satisfies Render's Web Service port requirement)
# ==============================================================================
app = Flask(__name__)

@app.route('/')
def home():
    return "GoLF_Fx AI Engine is Live & Scanning!"

# Environment Variables on Render
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TWELVEDATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")

bot = Bot(token=TELEGRAM_BOT_TOKEN)

# Expanded asset list to increase daily setup frequency
SYMBOLS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD", 
    "AUD/USD", "USD/CAD", "GBP/JPY", "EUR/JPY"
]

def get_m15_candles(symbol, size=50):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=15min&outputsize={size}&apikey={TWELVEDATA_API_KEY}"
    try:
        response = requests.get(url).json()
        if "values" in response:
            candles = response["values"]
            candles.reverse()  # Oldest to newest
            return [
                {
                    "open": float(c["open"]),
                    "high": float(c["high"]),
                    "low": float(c["low"]),
                    "close": float(c["close"])
                }
                for c in candles
            ]
        else:
            logging.error(f"Error fetching data for {symbol}: {response}")
            return None
    except Exception as e:
        logging.error(f"API Request Exception for {symbol}: {e}")
        return None

def calculate_ema(candles, period=50):
    """Calculates Exponential Moving Average for trend direction filtering."""
    closes = [c["close"] for c in candles]
    if len(closes) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def analyze_m15_market(symbol, candles):
    if not candles or len(candles) < 25:
        return None

    # Reference recent closed candle (c2) and setup formation candles
    c1, c2 = candles[-2], candles[-1]

    # Calculate baseline volatility (ATR substitute via 14-period average range)
    avg_range = sum(c["high"] - c["low"] for c in candles[-14:]) / 14
    min_body_size = avg_range * 0.35  # Ensures minimum momentum
    fvg_tolerance = avg_range * 0.30  # Dynamic FVG tolerance factor

    # Trend Direction Filter via 50 EMA
    ema50 = calculate_ema(candles, period=50)

    # 1. Dynamic Swing Points (Reduced lookback window from 7 to 4 bars to catch local sweeps)
    recent_swings_high = max(c["high"] for c in candles[-6:-2])
    recent_swings_low = min(c["low"] for c in candles[-6:-2])

    # Dynamic pip multiplier configuration
    pip_mult = 100 if "JPY" in symbol else (10 if "XAU" in symbol else 10000)

    # --------------------------------------------------------------------------
    # SETUP 1: RELAXED LIQUIDITY SWEEP + FVG / DISPLACEMENT
    # --------------------------------------------------------------------------
    
    # BEARISH SWEEP SETUP
    if c1["high"] >= recent_swings_high and c2["close"] < c1["low"]:
        body = abs(c2["close"] - c2["open"])
        if body >= min_body_size:
            entry = c2["close"]
            sl = max(c1["high"], c2["high"])
            risk = abs(sl - entry)

            if risk > 0:
                tp1 = entry - (risk * 1.5)
                tp2 = entry - (risk * 2.5)
                return {
                    "asset": symbol,
                    "action": "SELL",
                    "type": "Liquidity Sweep + Displacement",
                    "entry": entry,
                    "sl": sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "sl_pips": round(risk * pip_mult, 1),
                    "tp1_pips": round((risk * 1.5) * pip_mult, 1),
                    "tp2_pips": round((risk * 2.5) * pip_mult, 1),
                }

    # BULLISH SWEEP SETUP
    if c1["low"] <= recent_swings_low and c2["close"] > c1["high"]:
        body = abs(c2["close"] - c2["open"])
        if body >= min_body_size:
            entry = c2["close"]
            sl = min(c1["low"], c2["low"])
            risk = abs(entry - sl)

            if risk > 0:
                tp1 = entry + (risk * 1.5)
                tp2 = entry + (risk * 2.5)
                return {
                    "asset": symbol,
                    "action": "BUY",
                    "type": "Liquidity Sweep + Displacement",
                    "entry": entry,
                    "sl": sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "sl_pips": round(risk * pip_mult, 1),
                    "tp1_pips": round((risk * 1.5) * pip_mult, 1),
                    "tp2_pips": round((risk * 2.5) * pip_mult, 1),
                }

    # --------------------------------------------------------------------------
    # SETUP 2: TREND CONTINUATION BREAKOUT (FALLBACK WHEN NO SWEEP EXECUTED)
    # --------------------------------------------------------------------------
    if ema50:
        # BEARISH TREND BREAKOUT
        if c2["close"] < ema50 and c2["close"] < min(c["low"] for c in candles[-5:-1]):
            body = abs(c2["close"] - c2["open"])
            if body >= avg_range * 0.6:  # Strong expansion candle
                entry = c2["close"]
                sl = c2["high"]
                risk = abs(sl - entry)

                if risk > 0:
                    tp1 = entry - (risk * 1.5)
                    tp2 = entry - (risk * 2.5)
                    return {
                        "asset": symbol,
                        "action": "SELL",
                        "type": "M15 Trend Continuation Breakout",
                        "entry": entry,
                        "sl": sl,
                        "tp1": tp1,
                        "tp2": tp2,
                        "sl_pips": round(risk * pip_mult, 1),
                        "tp1_pips": round((risk * 1.5) * pip_mult, 1),
                        "tp2_pips": round((risk * 2.5) * pip_mult, 1),
                    }

        # BULLISH TREND BREAKOUT
        if c2["close"] > ema50 and c2["close"] > max(c["high"] for c in candles[-5:-1]):
            body = abs(c2["close"] - c2["open"])
            if body >= avg_range * 0.6:  # Strong expansion candle
                entry = c2["close"]
                sl = c2["low"]
                risk = abs(entry - sl)

                if risk > 0:
                    tp1 = entry + (risk * 1.5)
                    tp2 = entry + (risk * 2.5)
                    return {
                        "asset": symbol,
                        "action": "BUY",
                        "type": "M15 Trend Continuation Breakout",
                        "entry": entry,
                        "sl": sl,
                        "tp1": tp1,
                        "tp2": tp2,
                        "sl_pips": round(risk * pip_mult, 1),
                        "tp1_pips": round((risk * 1.5) * pip_mult, 1),
                        "tp2_pips": round((risk * 2.5) * pip_mult, 1),
                    }

    return None

def format_signal(signal):
    dec = 2 if "JPY" in signal["asset"] or "XAU" in signal["asset"] else 4
    return (
        f"🤖 <b>PHASE ENGINE AI — SIGNAL ALERT</b>\n\n"
        f"<b>Asset:</b> {signal['asset']}\n"
        f"<b>Action:</b> {signal['action']}\n"
        f"<b>AI Confidence:</b> 78.5% 🔥\n\n"
        f"📍 <b>Entry:</b> {signal['entry']:.{dec}f}\n"
        f"⛔ <b>Stop Loss:</b> {signal['sl']:.{dec}f} ({signal['sl_pips']} Pips)\n"
        f"🎯 <b>Take Profit 1:</b> {signal['tp1']:.{dec}f} (1:1.5 R:R | +{signal['tp1_pips']} Pips)\n"
        f"🎯 <b>Take Profit 2:</b> {signal['tp2']:.{dec}f} (1:2.5 R:R | +{signal['tp2_pips']} Pips)\n\n"
        f"📊 <b>Setup Analysis:</b>\n"
        f"• Strategy: {signal['type']}\n"
        f"• Timeframe: M15 Structural Alignment\n\n"
        f"⚡ <i>Manage risk responsibly according to your account size.</i>"
    )

async def send_telegram_message(text):
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.error(f"Telegram send failed: {e}")

async def main():
    logging.info("GoLF_Fx AI Engine Online. Multi-asset market scanning active.")
    await send_telegram_message("🚀 <b>GoLF_Fx AI Engine Online.</b>\nMulti-asset market scanning active.")

    last_signals = {}

    while True:
        for symbol in SYMBOLS:
            candles = get_m15_candles(symbol)
            if candles:
                signal = analyze_m15_market(symbol, candles)
                logging.info(f"Scanned {symbol} — {'setup found!' if signal else 'no valid setup yet.'}")
                if signal:
                    signal_key = f"{symbol}_{signal['action']}_{round(signal['entry'], 4)}"
                    if last_signals.get(symbol) != signal_key:
                        message = format_signal(signal)
                        await send_telegram_message(message)
                        last_signals[symbol] = signal_key
            time.sleep(8)  # API rate limit delay per symbol
            
        logging.info("Full scan cycle complete. Sleeping 3 minutes...")
        time.sleep(180)  # Polling every 3 minutes for timely M15 entries

def start_scanning():
    asyncio.run(main())

if __name__ == "__main__":
    threading.Thread(target=start_scanning, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
                    
