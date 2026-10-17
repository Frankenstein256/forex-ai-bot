import os
import time
import requests
import pandas as pd
import yfinance as yf

# ==========================================
# SECRETS & CONFIGURATION
# ==========================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Pair mappings for market data
SYMBOLS = {
    "XAU/USD": "GC=F",
    "EUR/USD": "EURUSD=X",
    "USD/JPY": "JPY=X"
}

# Custom headers to bypass Yahoo Finance scraping blocks
CUSTOM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ==========================================
# TELEGRAM ALERT ENGINE
# ==========================================
def send_telegram_alert(asset, action, confidence, entry, stop_loss, tp1, tp2, strategy, timeframe):
    """
    Formats and posts the signal alert matching the PHASE ENGINE AI template.
    """
    is_gold = "XAU" in asset
    multiplier = 10 if is_gold else 10000

    sl_pips = abs(round((entry - stop_loss) * multiplier, 1))
    tp1_pips = abs(round((tp1 - entry) * multiplier, 1))
    tp2_pips = abs(round((tp2 - entry) * multiplier, 1))

    decimals = 2 if is_gold else 5

    message = f"""🤖 *PHASE ENGINE AI – SIGNAL ALERT*

*Asset:* `{asset}`
*Action:* `{action}`
*AI Confidence:* `{confidence:.1f}%` 🔥

📍 *Entry:* `{entry:.{decimals}f}`
⛔ *Stop Loss:* `{stop_loss:.{decimals}f}` ({sl_pips} Pips)
🎯 *Take Profit 1:* `{tp1:.{decimals}f}` (1:2 R:R | +{tp1_pips} Pips)
🎯 *Take Profit 2:* `{tp2:.{decimals}f}` (1:3 R:R | +{tp2_pips} Pips)

📊 *Setup Analysis:*
• Strategy: {strategy}
• Timeframe: {timeframe}

⚡ *Manage risk responsibly according to your account size.*"""

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        res = requests.post(url, json=payload, timeout=10)
        print(f"[{asset}] Telegram Alert Status: {res.status_code}")
    except Exception as e:
        print(f"Error sending Telegram alert for {asset}: {e}")

# ==========================================
# STRATEGY SCANNER (Liquidity Sweeps + FVG)
# ==========================================
def analyze_market(symbol_label, ticker_symbol):
    """
    Downloads M15 data and checks for Liquidity Sweeps + Fair Value Gap alignments.
    """
    print(f"Scanning {symbol_label}...")

    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.history(period="5d", interval="15m")
    except Exception as e:
        print(f"Failed to download data for {symbol_label}: {e}")
        return

    if df.empty or len(df) < 15:
        print(f"Insufficient data returned for {symbol_label}")
        return

    # Standardize column naming
    df.columns = [col.lower() for col in df.columns]

    latest = df.iloc[-1]
    prev_1 = df.iloc[-2]
    prev_3 = df.iloc[-4]

    # 1. Bullish Setup (Liquidity Sweep + FVG)
    recent_low = df['low'].iloc[-12:-2].min()
    liquidity_sweep_buy = (prev_1['low'] < recent_low) and (prev_1['close'] > recent_low)
    fvg_buy = prev_1['low'] > prev_3['high']

    if liquidity_sweep_buy or fvg_buy:
        entry = float(latest['close'])
        buffer = 1.5 if "XAU" in symbol_label else 0.0008
        stop_loss = float(df['low'].iloc[-5:].min()) - buffer
        risk = entry - stop_loss

        if risk > 0:
            tp1 = entry + (risk * 2)
            tp2 = entry + (risk * 3)
            confidence = 75.0 if (liquidity_sweep_buy and fvg_buy) else 68.5

            send_telegram_alert(
                asset=symbol_label,
                action="BUY",
                confidence=confidence,
                entry=entry,
                stop_loss=stop_loss,
                tp1=tp1,
                tp2=tp2,
                strategy="Liquidity Sweep + Fair Value Gap",
                timeframe="M15 Structural Alignment"
            )
            return

    # 2. Bearish Setup (Liquidity Sweep + FVG)
    recent_high = df['high'].iloc[-12:-2].max()
    liquidity_sweep_sell = (prev_1['high'] > recent_high) and (prev_1['close'] < recent_high)
    fvg_sell = prev_1['high'] < prev_3['low']

    if liquidity_sweep_sell or fvg_sell:
        entry = float(latest['close'])
        buffer = 1.5 if "XAU" in symbol_label else 0.0008
        stop_loss = float(df['high'].iloc[-5:].max()) + buffer
        risk = stop_loss - entry

        if risk > 0:
            tp1 = entry - (risk * 2)
            tp2 = entry - (risk * 3)
            confidence = 75.0 if (liquidity_sweep_sell and fvg_sell) else 68.5

            send_telegram_alert(
                asset=symbol_label,
                action="SELL",
                confidence=confidence,
                entry=entry,
                stop_loss=stop_loss,
                tp1=tp1,
                tp2=tp2,
                strategy="Liquidity Sweep + Fair Value Gap",
                timeframe="M15 Structural Alignment"
            )
            return

    print(f"No active setup found for {symbol_label}.")

# ==========================================
# SCRIPT EXECUTION
# ==========================================
if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID secrets in GitHub Settings!")

    for label, ticker in SYMBOLS.items():
        analyze_market(label, ticker)
        time.sleep(1)  # Brief pause between symbol requests
    
