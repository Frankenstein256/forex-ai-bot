"""
report.py
---------
DIAGNOSTIC ONLY - reads trade_history.jsonl (resolved paper trades)
and prints performance stats. Does not change any files, does not
affect the live bot.

Run manually via the "Trade Performance Report" GitHub Actions
workflow - results print directly to the job log.
"""

import json
import os
from collections import defaultdict

from config import TRADE_HISTORY_FILE


def load_trades():
    if not os.path.exists(TRADE_HISTORY_FILE):
        return []
    trades = []
    with open(TRADE_HISTORY_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                trades.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return trades


def compute_stats(trades):
    if not trades:
        return None

    wins = [t for t in trades if t["outcome"] == "win"]
    losses = [t for t in trades if t["outcome"] == "loss"]
    net_r = sum(t["outcome_r"] for t in trades)
    win_rate = len(wins) / len(trades) * 100

    gross_win_r = sum(t["outcome_r"] for t in wins)
    gross_loss_r = abs(sum(t["outcome_r"] for t in losses))
    profit_factor = (gross_win_r / gross_loss_r) if gross_loss_r > 0 else float("inf")

    expectancy = net_r / len(trades)

    # Running drawdown (in R) across the trade sequence, in the order recorded
    running = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for t in trades:
        running += t["outcome_r"]
        peak = max(peak, running)
        max_drawdown = min(max_drawdown, running - peak)

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "net_r": net_r,
        "expectancy": expectancy,
        "profit_factor": profit_factor,
        "max_drawdown_r": max_drawdown,
    }


def print_report(all_trades):
    print("=" * 60)
    print("PAPER TRADE PERFORMANCE REPORT")
    print("=" * 60)
    print("This reflects REAL tracked outcomes since paper trading was")
    print("enabled - not a backtest, not a guess. Every signal sent has")
    print("been followed forward to an actual win/loss against real")
    print("closed candles.\n")

    if not all_trades:
        print("No resolved trades yet. Trades are tracked from the moment")
        print("a signal is sent until price hits either the stop or the")
        print("target - check back once some have had time to resolve.")
        return

    overall = compute_stats(all_trades)
    print(f"OVERALL ({overall['total_trades']} resolved trades)")
    print(f"  Win rate:      {overall['win_rate']:.1f}%  ({overall['wins']}W / {overall['losses']}L)")
    print(f"  Net R:         {overall['net_r']:+.2f}")
    print(f"  Expectancy:    {overall['expectancy']:+.3f} R per trade")
    print(f"  Profit factor: {overall['profit_factor']:.2f}")
    print(f"  Max drawdown:  {overall['max_drawdown_r']:.2f} R")

    if overall["total_trades"] < 30:
        print(f"\n  NOTE: sample size is small ({overall['total_trades']} trades).")
        print("  Treat these numbers as an early read, not a proven edge.")
        print("  Statistical confidence improves significantly past ~30-50 trades.")

    by_symbol = defaultdict(list)
    for t in all_trades:
        by_symbol[t["symbol"]].append(t)

    print(f"\n{'-'*60}")
    print("BY SYMBOL")
    print(f"{'-'*60}")
    for symbol, trades in by_symbol.items():
        s = compute_stats(trades)
        print(f"\n{symbol} ({s['total_trades']} trades)")
        print(f"  Win rate: {s['win_rate']:.1f}%  Net R: {s['net_r']:+.2f}  "
              f"Expectancy: {s['expectancy']:+.3f} R/trade")


def main():
    trades = load_trades()
    print_report(trades)


if __name__ == "__main__":
    main()
