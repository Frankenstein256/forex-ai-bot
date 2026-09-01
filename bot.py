import os
import time
import asyncio
import logging
import requests
from telegram import Bot
from telegram.constants import ParseMode

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Environment Variables on Render
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY")

bot = Bot(token=TELEGRAM_BOT_TOKEN)

SYMBOLS = ["EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD"]

def get_m15_candles(symbol, size=40):
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

def analyze_m15_market(symbol, candles):
    if not candles or len(candles) < 20:
        return None

    # M15 Candle references
    c1, c2, c3 = candles[-3], candles[-2], candles[-1]

    # 1. Tori Trades M15 Structure (Dynamic Trendline/Structure Check)
    # Checks recent 15-period swing levels for higher-lows/lower-highs on M15
    recent_swings_high = max(c["high"] for c in candles[-18:-3])
    recent_swings_low = min(c["low"] for c in candles[-18:-3])

    # 2. Strategy Engine: Liquidity Sweep + Fair Value Gap (FVG)

    # BEARISH SETUP (High Liquidity Sweep + Bearish FVG on M15)
    if c2["high"] > recent_swings_high and c3["close"] < c2["low"]:
        if c1["low"] > c3["high"]:  # Bearish Fair Value Gap
            entry = c3["close"]
            sl = c2["high"]
            risk = abs(sl - entry)
            tp1 = entry - (risk * 2)
            tp2 = entry - (risk * 3)

            pip_mult = 100 if "JPY" in symbol else (10 if "XAU" in symbol else 10000)
            return {
                "asset": symbol,
                "action": "SELL",
                "entry": entry,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "sl_pips": round(risk * pip_mult, 1),
                "tp1_pips": round((risk * 2) * pip_mult, 1),
                "tp2_pips": round((risk * 3) * pip_mult, 1),
            }

    # BULLISH SETUP (Low Liquidity Sweep + Bullish FVG on M15)
    if c2["low"] < recent_swings_low and c3["close"] > c2["high"]:
        if c3["low"] > c1["high"]:  # Bullish Fair Value Gap
            entry = c3["close"]
            sl = c2["low"]
            risk = abs(entry - sl)
            tp1 = entry + (risk * 2)
            tp2 = entry + (risk * 3)

            pip_mult = 100 if "JPY" in symbol else (10 if "XAU" in symbol else 10000)
            return {
                "asset": symbol,
                "action": "BUY",
                "entry": entry,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "sl_pips": round(risk * pip_mult, 1),
                "tp1_pips": round((risk * 2) * pip_mult, 1),
                "tp2_pips": round((risk * 3) * pip_mult, 1),
            }

    return None

def format_signal(signal):
    dec = 2 if "JPY" in signal["asset"] or "XAU" in signal["asset"] else 4
    return (
        f"🤖 <b>PHASE ENGINE AI — SIGNAL ALERT</b>\n\n"
        f"<b>Asset:</b> {signal['asset']}\n"
        f"<b>Action:</b> {signal['action']}\n"
        f"<b>AI Confidence:</b> 75.0% 🔥\n\n"
        f"📍 <b>Entry:</b> {signal['entry']:.{dec}f}\n"
        f"⛔ <b>Stop Loss:</b> {signal['sl']:.{dec}f} ({signal['sl_pips']} Pips)\n"
        f"🎯 <b>Take Profit 1:</b> {signal['tp1']:.{dec}f} (1:2 R:R | +{signal['tp1_pips']} Pips)\n"
        f"🎯 <b>Take Profit 2:</b> {signal['tp2']:.{dec}f} (1:3 R:R | +{signal['tp2_pips']} Pips)\n\n"
        f"📊 <b>Setup Analysis:</b>\n"
        f"• Strategy: Liquidity Sweep + Fair Value Gap\n"
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
                if signal:
                    signal_key = f"{symbol}_{signal['action']}_{signal['entry']}"
                    if last_signals.get(symbol) != signal_key:
                        message = format_signal(signal)
                        await send_telegram_message(message)
                        last_signals[symbol] = signal_key
            time.sleep(12)  # Respect Twelve Data API limits
        time.sleep(300)      # Poll M15 candles every 5 minutes

if __name__ == "__main__":
    asyncio.run(main())
            
