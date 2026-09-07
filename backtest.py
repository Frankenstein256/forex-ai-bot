"""
backtest.py
-----------
Tests the strategy against HISTORICAL data to see how often it
would have fired a signal, and whether those signals would have
made money.

HOW THIS AVOIDS CHEATING (look-ahead bias):
At each point in time, we only show the strategy candles that would
have ALREADY happened by that point - never future ones. This is
what "walk-forward" means. If we let the strategy see the future,
the results would look great but be completely fake.

HOW WE JUDGE A TRADE'S OUTCOME:
Once a signal fires, we walk forward candle-by-candle checking if
price hits the Stop Loss or Take Profit first. If a single candle's
range touches BOTH levels, we conservatively assume the Stop was
hit first (since we can't know the true order within that candle).

This is NOT a perfect simulation of real trading (no real spread
variation, no slippage, assumes you get filled exactly at signal
price) - it's a first honest look at whether the underlying logic
has any edge at all.
"""

import csv
import os

from config import PAIRS, MIN_SCORE, MIN_RR
from data_feed import get_candles
from strategy import evaluate_setup

# How many historical M15 candles to pull per symbol.
# TwelveData's free plan limits how many you can pull per request,
# so start modest and raise it once you confirm your plan's limit.
BACKTEST_BARS = int(os.getenv("BACKTEST_BARS", "3000"))

LOOKBACK_WINDOW = 60  # how many recent candles the strategy gets to see at each step


def simulate_trade_outcome(m15_candles, start_index, setup):
    """
    Walks forward from the candle AFTER the signal, checking each
    candle to see if price hits the stop or the target first.
    Returns the R-multiple result (+setup.rr for a win, -1 for a loss),
    or None if we ran out of data before it resolved.
    """
    for candle in m15_candles[start_index + 1:]:
        hit_stop = False
        hit_target = False

        if setup.direction == "long":
            hit_stop = candle["low"] <= setup.stop
            hit_target = candle["high"] >= setup.target
        else:
            hit_stop = candle["high"] >= setup.stop
            hit_target = candle["low"] <= setup.target

        if hit_stop and hit_target:
            return -1.0  # conservative: assume stop hit first
        if hit_stop:
            return -1.0
        if hit_target:
            return setup.rr

    return None  # trade never resolved within the data we have


def backtest_pair(pair_config, min_score, min_rr):
    symbol = pair_config["symbol"]
    smt_symbol = pair_config["smt_symbol"]

    print(f"\nFetching historical data for {symbol}...")
    h4_all = get_candles(symbol, "4h", output_size=BACKTEST_BARS // 4)
    m15_all = get_candles(symbol, "15min", output_size=BACKTEST_BARS)

    comparison_all = None
    if smt_symbol:
        comparison_all = get_candles(smt_symbol, "15min", output_size=BACKTEST_BARS)

    results = []
    open_trade = None  # only one open trade at a time per symbol, like live paper trading

    for i in range(LOOKBACK_WINDOW, len(m15_all)):
        current_time = m15_all[i]["time"]

        # Resolve any open trade first
        if open_trade is not None:
            outcome = simulate_trade_outcome(m15_all, open_trade["index"], open_trade["setup"])
            if outcome is not None:
                results.append({
                    "symbol": symbol,
                    "time": open_trade["setup_time"],
                    "direction": open_trade["setup"].direction,
                    "score": open_trade["setup"].score,
                    "rr": open_trade["setup"].rr,
                    "outcome_r": outcome,
                })
                open_trade = None
            continue  # don't look for a new signal while one is open

        # Build the "as of now" slices - only candles up to (and including) this point
        h4_slice = [c for c in h4_all if c["time"] <= current_time][-LOOKBACK_WINDOW:]
        m15_slice = m15_all[max(0, i - LOOKBACK_WINDOW):i + 1]
        comparison_slice = None
        if comparison_all:
            comparison_slice = [c for c in comparison_all if c["time"] <= current_time][-LOOKBACK_WINDOW:]

        if len(h4_slice) < 10 or len(m15_slice) < 20:
            continue  # not enough history yet to evaluate

        setup = evaluate_setup(h4_slice, m15_slice, comparison_slice, min_score, min_rr,
                                comparison_label=smt_symbol or "none")

        if setup is not None:
            open_trade = {"index": i, "setup": setup, "setup_time": current_time}

    return results


def build_report(all_results):
    """
    Builds the report as a string (instead of just printing it),
    so it can be shown on a webpage OR printed to a terminal.
    """
    lines = []
    lines.append("=" * 50)
    lines.append("BACKTEST REPORT")
    lines.append("=" * 50)

    if not all_results:
        lines.append("No signals were generated at all during this period.")
        lines.append("That likely means MIN_SCORE is too strict for this data,")
        lines.append("or the strategy conditions rarely align. Try lowering MIN_SCORE and re-running.")
        return "\n".join(lines)

    by_symbol = {}
    for r in all_results:
        by_symbol.setdefault(r["symbol"], []).append(r)

    for symbol, results in by_symbol.items():
        wins = [r for r in results if r["outcome_r"] > 0]
        losses = [r for r in results if r["outcome_r"] <= 0]
        net_r = sum(r["outcome_r"] for r in results)
        win_rate = len(wins) / len(results) * 100 if results else 0
        expectancy = net_r / len(results) if results else 0

        lines.append(f"\n--- {symbol} ---")
        lines.append(f"Total signals:  {len(results)}")
        lines.append(f"Wins:           {len(wins)}")
        lines.append(f"Losses:         {len(losses)}")
        lines.append(f"Win rate:       {win_rate:.1f}%")
        lines.append(f"Net R:          {net_r:.2f}")
        lines.append(f"Expectancy:     {expectancy:.3f} R per trade")

        if len(results) < 30:
            lines.append("WARNING: Sample size is small - treat these numbers as very rough, not proof of an edge.")

    return "\n".join(lines)


def print_report(all_results):
    print(build_report(all_results))

    # Save full detail to CSV so you can inspect every single signal
    if all_results:
        with open("backtest_results.csv", "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["symbol", "time", "direction", "score", "rr", "outcome_r"])
            writer.writeheader()
            writer.writerows(all_results)
        print("\nFull signal-by-signal detail saved to backtest_results.csv")


def run_full_backtest():
    """
    Runs the backtest across all configured pairs and returns
    (all_results, report_string). Used by both the CLI (main below)
    and the web endpoint in main.py.
    """
    all_results = []
    errors = []
    for pair_config in PAIRS:
        try:
            results = backtest_pair(pair_config, MIN_SCORE, MIN_RR)
            all_results.extend(results)
        except Exception as e:
            errors.append(f"Could not backtest {pair_config['symbol']}: {e}")

    report = build_report(all_results)
    if errors:
        report += "\n\n" + "\n".join(errors)
    return all_results, report


def main():
    all_results, report = run_full_backtest()
    print_report(all_results)


if __name__ == "__main__":
    main()
