"""
strategy.py
-----------
This is the brain of the bot. It looks at candle data and tries to
detect the setup you described: HTF bias + liquidity sweep + SMT
divergence + FVG/IFVG retracement + displacement.

IMPORTANT HONESTY NOTE (read this, bro):
Concepts like "liquidity sweep", "SMT", "FVG" are NOT perfectly
precise math - real traders use discretion and experience to spot
them. What's below is an ENGINEERING APPROXIMATION of those ideas.
It will not perfectly match what you'd circle on a chart by eye.
That's exactly why we backtest and forward-test before trusting it
with real money - to see if this approximation actually works.
"""

from dataclasses import dataclass
from typing import List, Dict, Optional


@dataclass
class Setup:
    direction: str          # "long" or "short"
    score: int
    reasons: List[str]
    entry: float
    stop: float
    target: float
    rr: float


# ---------- 1. Higher-timeframe bias ----------

def get_htf_bias(h4_candles: List[Dict]) -> str:
    """
    Very simplified structure read: look at the last 10 H4 candles.
    If closes are generally trending up -> "bullish"
    If generally trending down -> "bearish"
    Otherwise -> "neutral"
    """
    recent = h4_candles[-10:]
    closes = [c["close"] for c in recent]
    first_half_avg = sum(closes[:5]) / 5
    second_half_avg = sum(closes[5:]) / 5

    diff = second_half_avg - first_half_avg
    threshold = (max(closes) - min(closes)) * 0.15  # noise buffer

    if diff > threshold:
        return "bullish"
    elif diff < -threshold:
        return "bearish"
    return "neutral"


# ---------- 2. Liquidity sweep ----------

def detect_liquidity_sweep(m15_candles: List[Dict], direction: str) -> bool:
    """
    A "sweep" here means: price pokes below a recent swing low (for
    a long setup) or above a recent swing high (for a short setup)
    with a wick, then closes back inside the range.
    """
    lookback = m15_candles[-20:-1]  # exclude the very last candle
    last = m15_candles[-1]

    if direction == "long":
        swing_low = min(c["low"] for c in lookback)
        wicked_below = last["low"] < swing_low
        closed_back_inside = last["close"] > swing_low
        return wicked_below and closed_back_inside

    if direction == "short":
        swing_high = max(c["high"] for c in lookback)
        wicked_above = last["high"] > swing_high
        closed_back_inside = last["close"] < swing_high
        return wicked_above and closed_back_inside

    return False


# ---------- 3. SMT divergence ----------

def detect_smt_divergence(primary: List[Dict], comparison: Optional[List[Dict]], direction: str) -> bool:
    """
    SMT divergence (simplified): the primary pair (e.g. EURUSD) sweeps a
    swing point, but the comparison pair (e.g. GBPUSD) does NOT sweep the
    equivalent point. That mismatch suggests hidden strength/weakness.

    If no comparison pair is configured (comparison is None), this
    confluence is simply skipped - it does not count for or against
    the setup.
    """
    if comparison is None:
        return False

    p_lookback = primary[-20:-1]
    c_lookback = comparison[-20:-1]
    p_last = primary[-1]
    c_last = comparison[-1]

    if direction == "long":
        p_swept = p_last["low"] < min(c["low"] for c in p_lookback)
        c_swept = c_last["low"] < min(c["low"] for c in c_lookback)
        return p_swept and not c_swept

    if direction == "short":
        p_swept = p_last["high"] > max(c["high"] for c in p_lookback)
        c_swept = c_last["high"] > max(c["high"] for c in c_lookback)
        return p_swept and not c_swept

    return False


# ---------- 4. Fair Value Gap (FVG) ----------

def find_fvgs(m15_candles: List[Dict], direction: str) -> List[Dict]:
    """
    A bullish FVG: candle[0]'s high is below candle[2]'s low (a gap).
    A bearish FVG: candle[0]'s low is above candle[2]'s high.
    Returns a list of gap zones found in the recent candles.
    """
    fvgs = []
    for i in range(len(m15_candles) - 2):
        c0, c2 = m15_candles[i], m15_candles[i + 2]
        if direction == "long" and c0["high"] < c2["low"]:
            fvgs.append({"top": c2["low"], "bottom": c0["high"], "index": i})
        if direction == "short" and c0["low"] > c2["high"]:
            fvgs.append({"top": c0["low"], "bottom": c2["high"], "index": i})
    return fvgs


def detect_ifvg_retracement(m15_candles: List[Dict], direction: str) -> bool:
    """
    Simplified IFVG-style check: has price retraced back into any
    recent FVG zone (a common retracement/entry area) after the sweep?
    """
    fvgs = find_fvgs(m15_candles[-15:], direction)
    if not fvgs:
        return False

    last_close = m15_candles[-1]["close"]
    for gap in fvgs:
        if gap["bottom"] <= last_close <= gap["top"]:
            return True
    return False


# ---------- 5. Displacement ----------

def detect_displacement(m15_candles: List[Dict]) -> bool:
    """
    Displacement = a candle with an unusually large body compared to
    recent average - suggests aggressive institutional-style entry.
    """
    recent = m15_candles[-15:]
    bodies = [abs(c["close"] - c["open"]) for c in recent]
    avg_body = sum(bodies[:-1]) / max(len(bodies) - 1, 1)
    last_body = bodies[-1]
    return last_body > avg_body * 1.8


# ---------- 6. Trade levels ----------

def compute_trade_levels(m15_candles: List[Dict], direction: str):
    entry = m15_candles[-1]["close"]
    lookback = m15_candles[-20:]

    if direction == "long":
        stop = min(c["low"] for c in lookback)
        risk = entry - stop
        target = entry + risk * 3  # aiming for ~1:3, adjust via MIN_RR check
    else:
        stop = max(c["high"] for c in lookback)
        risk = stop - entry
        target = entry - risk * 3

    if risk <= 0:
        return None

    rr = abs(target - entry) / risk
    return entry, stop, target, rr


# ---------- 7. Put it all together ----------

def evaluate_setup(symbol_h4, symbol_m15, comparison_m15, min_score: int, min_rr: float,
                    comparison_label: str = "comparison pair") -> Optional[Setup]:
    """
    symbol_h4 / symbol_m15: candles for the pair we're actually trading
    comparison_m15: candles for the SMT comparison pair, or None if
                    no comparison pair is configured for this symbol
    """
    bias = get_htf_bias(symbol_h4)
    if bias == "neutral":
        return None  # no clear directional lean, skip

    direction = "long" if bias == "bullish" else "short"
    reasons = [f"HTF bias: {bias}"]
    score = 1

    if detect_liquidity_sweep(symbol_m15, direction):
        score += 2
        reasons.append("Liquidity sweep detected")

    if detect_smt_divergence(symbol_m15, comparison_m15, direction):
        score += 2
        reasons.append(f"SMT divergence vs {comparison_label}")

    if detect_ifvg_retracement(symbol_m15, direction):
        score += 2
        reasons.append("Retracement into FVG/IFVG zone")

    if detect_displacement(symbol_m15):
        score += 1
        reasons.append("Displacement candle present")

    if score < min_score:
        return None

    levels = compute_trade_levels(symbol_m15, direction)
    if levels is None:
        return None
    entry, stop, target, rr = levels

    if rr < min_rr:
        return None

    return Setup(
        direction=direction,
        score=score,
        reasons=reasons,
        entry=entry,
        stop=stop,
        target=target,
        rr=rr,
    )
