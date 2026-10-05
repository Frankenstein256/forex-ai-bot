"""
strategy.py
-----------
Optimized Smart Money Concepts (SMC) & ICT Strategy Engine.
Combines HTF Trend, Killzone Timing, Sweeps, MSS, FVGs, and Displacement.
"""

from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime, time

from config import RR_MULTIPLE


@dataclass
class Setup:
    direction: str          # "long" or "short"
    score: int
    score_normalized: int   # 0-100 scale
    max_possible_score: int
    reasons: List[str]
    entry: float
    stop: float
    target: float
    rr: float


# ---------- 1. Session Timing (Killzones) ----------

def is_in_killzone(current_time: Optional[datetime] = None) -> bool:
    """
    Checks if current UTC time falls within London or New York Killzones.
    London: 07:00 - 10:00 UTC
    New York: 12:00 - 15:00 UTC
    """
    now = current_time.time() if current_time else datetime.utcnow().time()
    
    london_start, london_end = time(7, 0), time(10, 0)
    ny_start, ny_end = time(12, 0), time(15, 0)

    in_london = london_start <= now <= london_end
    in_ny = ny_start <= now <= ny_end

    return in_london or in_ny


# ---------- 2. HTF Trend Context ----------

def get_htf_bias(h4_candles: List[Dict]) -> str:
    recent = h4_candles[-10:]
    closes = [c["close"] for c in recent]
    first_half_avg = sum(closes[:5]) / 5
    second_half_avg = sum(closes[5:]) / 5

    diff = second_half_avg - first_half_avg
    threshold = (max(closes) - min(closes)) * 0.15

    if diff > threshold:
        return "bullish"
    elif diff < -threshold:
        return "bearish"
    return "neutral"


# ---------- 3. Liquidity Sweep + Market Structure Shift (MSS) ----------

def detect_sweep_and_mss(m15_candles: List[Dict], direction: str) -> tuple[bool, Optional[float]]:
    """
    Checks if price swept liquidity AND caused a structural shift (MSS).
    Returns (True/False, stop_loss_price).
    """
    lookback = m15_candles[-20:-1]
    last = m15_candles[-1]

    if direction == "long":
        swing_low = min(c["low"] for c in lookback)
        wicked_below = last["low"] < swing_low
        closed_above_open = last["close"] > last["open"]
        if wicked_below and closed_above_open:
            return True, last["low"]  # Stop loss set at sweep low

    if direction == "short":
        swing_high = max(c["high"] for c in lookback)
        wicked_above = last["high"] > swing_high
        closed_below_open = last["close"] < last["open"]
        if wicked_above and closed_below_open:
            return True, last["high"]  # Stop loss set at sweep high

    return False, None


# ---------- 4. Fair Value Gap (FVG) ----------

def detect_fvg(m15_candles: List[Dict], direction: str) -> bool:
    recent = m15_candles[-5:]
    for i in range(len(recent) - 2):
        c0, c2 = recent[i], recent[i + 2]
        if direction == "long" and c0["high"] < c2["low"]:
            return True
        if direction == "short" and c0["low"] > c2["high"]:
            return True
    return False


# ---------- 5. Displacement ----------

def detect_displacement(m15_candles: List[Dict]) -> bool:
    recent = m15_candles[-15:]
    bodies = [abs(c["close"] - c["open"]) for c in recent]
    avg_body = sum(bodies[:-1]) / max(len(bodies) - 1, 1)
    last_body = bodies[-1]
    return last_body > avg_body * 1.8


# ---------- 6. Strategy Evaluator ----------

def evaluate_setup(symbol_h4: List[Dict], symbol_m15: List[Dict], comparison_m15: Optional[List[Dict]], 
                   min_score: int = 5, min_rr: float = 2.0) -> Optional[Setup]:
    
    # Killzone Check
    if not is_in_killzone():
        return None

    bias = get_htf_bias(symbol_h4)
    if bias == "neutral":
        return None

    direction = "long" if bias == "bullish" else "short"
    reasons = [f"HTF Bias: {bias}"]
    score = 1

    # Check Sweep & Structural Shift
    has_sweep, sweep_stop = detect_sweep_and_mss(symbol_m15, direction)
    if not has_sweep:
        return None  # Hard Requirement
    score += 2
    reasons.append("Liquidity Sweep + Structural Reversal")

    # Check FVG Imbalance
    if detect_fvg(symbol_m15, direction):
        score += 2
        reasons.append("FVG Imbalance present")

    # Check Displacement
    if detect_displacement(symbol_m15):
        score += 1
        reasons.append("Strong Displacement Candle")

    # Price levels setup
    entry = symbol_m15[-1]["close"]
    stop = sweep_stop if sweep_stop else (entry * 0.995 if direction == "long" else entry * 1.005)
    
    risk = abs(entry - stop)
    if risk == 0:
        return None

    target = entry + (risk * RR_MULTIPLE) if direction == "long" else entry - (risk * RR_MULTIPLE)
    rr = abs(target - entry) / risk

    if rr < min_rr:
        return None

    max_possible_score = 6
    score_normalized = round((score / max_possible_score) * 100)

    return Setup(
        direction=direction,
        score=score,
        score_normalized=score_normalized,
        max_possible_score=max_possible_score,
        reasons=reasons,
        entry=round(entry, 5),
        stop=round(stop, 5),
        target=round(target, 5),
        rr=round(rr, 2),
    )
    
