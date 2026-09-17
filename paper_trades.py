"""
paper_trades.py
----------------
Handles the paper trade lifecycle: SIGNAL -> OPEN -> MONITOR -> TP/SL
-> WIN/LOSS -> R -> written to trade history.

WHY THIS EXISTS:
Up to now, the bot could tell you a setup was found, but never
followed up on whether that setup actually would have made money.
This closes that loop - every signal that goes out gets tracked
forward in time against REAL subsequent closed candles until it
resolves, so we get an honest, measured win rate instead of a guess.

HOW OUTCOMES ARE DECIDED (same conservative rule as backtest.py):
We walk forward through closed M15 candles after the trade was
opened. If a single candle's range touches BOTH the stop and the
target, we conservatively assume the stop was hit first, since OHLC
data alone can't tell us the true order within that candle.

STATE:
- paper_trades.json  - trades currently open, being monitored
- trade_history.jsonl - trades that have resolved (win or loss)
"""

import json
import os

from config import PAPER_TRADES_FILE, TRADE_HISTORY_FILE, TRADE_HISTORY_MAX_LINES


def load_open_trades():
    if not os.path.exists(PAPER_TRADES_FILE):
        return []
    with open(PAPER_TRADES_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def save_open_trades(trades):
    with open(PAPER_TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)


def append_trade_history(record: dict):
    lines = []
    if os.path.exists(TRADE_HISTORY_FILE):
        with open(TRADE_HISTORY_FILE, "r") as f:
            lines = f.readlines()
    lines.append(json.dumps(record) + "\n")
    if len(lines) > TRADE_HISTORY_MAX_LINES:
        lines = lines[-TRADE_HISTORY_MAX_LINES:]
    with open(TRADE_HISTORY_FILE, "w") as f:
        f.writelines(lines)


def open_trade(signal: dict, opened_at_candle_time: str):
    """
    Creates a new open paper trade from a signal dict (same shape used
    for Telegram messages - signal_id, symbol, direction, entry, stop,
    target, rr, score, score_normalized, reasons).
    """
    return {
        "signal_id": signal["signal_id"],
        "symbol": signal["symbol"],
        "direction": signal["direction"],
        "entry": signal["entry"],
        "stop": signal["stop"],
        "target": signal["target"],
        "rr": signal["rr"],
        "score": signal["score"],
        "score_normalized": signal.get("score_normalized"),
        "max_possible_score": signal.get("max_possible_score"),
        "reasons": signal["reasons"],
        "opened_at_candle_time": opened_at_candle_time,
    }


def check_trade_against_candles(trade: dict, m15_candles: list):
    """
    Walks forward through m15_candles looking for the FIRST candle
    strictly after the trade's opened_at_candle_time that resolves it
    (touches stop and/or target). Returns a result dict if resolved,
    or None if still open (no resolving candle in this batch yet).

    Conservative rule: if one candle touches both, stop wins.
    """
    opened_time = trade["opened_at_candle_time"]
    direction = trade["direction"]
    stop = trade["stop"]
    target = trade["target"]

    for candle in m15_candles:
        if candle["time"] <= opened_time:
            continue  # only look at candles AFTER the trade was opened

        if direction == "long":
            hit_stop = candle["low"] <= stop
            hit_target = candle["high"] >= target
        else:
            hit_stop = candle["high"] >= stop
            hit_target = candle["low"] <= target

        if hit_stop:
            return {"outcome": "loss", "outcome_r": -1.0, "exit_price": stop, "exit_time": candle["time"]}
        if hit_target:
            return {"outcome": "win", "outcome_r": trade["rr"], "exit_price": target, "exit_time": candle["time"]}

    return None  # not resolved yet with the data we currently have
