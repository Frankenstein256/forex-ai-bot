"""
ai_filter.py
------------
Uses Gemini AI to audit and filter strategy setups before dispatching.
"""

import os
from typing import List, Dict
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

import config
from strategy import Setup

# Initialize Gemini Client using API key from config or environment
client = genai.Client(api_key=getattr(config, "GEMINI_API_KEY", os.getenv("GEMINI_API_KEY")))


class AIEvaluation(BaseModel):
    approve_trade: bool = Field(
        description="True if setup represents a high-probability trade according to market structure."
    )
    confidence_score: int = Field(
        description="Confidence score from 0 to 100 based on setup quality and lack of red flags."
    )
    ai_confluences: List[str] = Field(
        description="Bullet points detailing structural confirmations."
    )
    risk_notes: str = Field(
        description="Assessment of potential risks or counter-trend warnings."
    )


def filter_setup_with_ai(
    symbol: str, 
    setup: Setup, 
    m15_recent_candles: List[Dict], 
    h4_recent_candles: List[Dict]
) -> AIEvaluation:
    """
    Sends the generated Setup object and recent candle context to Gemini Flash 2.5
    for an AI trade filter and confirmation audit.
    """
    recent_m15_summary = [
        {"open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]} 
        for c in m15_recent_candles[-5:]
    ]
    recent_h4_summary = [
        {"high": c["high"], "low": c["low"], "close": c["close"]} 
        for c in h4_recent_candles[-5:]
    ]

    prompt = f"""
    You are an expert quantitative and institutional ICT/Smart Money Concepts forex analyst.
    
    A rule-based algorithm generated the following trade setup:
    - Symbol: {symbol}
    - Direction: {setup.direction.upper()}
    - Rule-based Score: {setup.score_normalized}/100
    - Calculated Entry: {setup.entry}
    - Calculated Stop Loss: {setup.stop}
    - Calculated Take Profit: {setup.target}
    - Risk/Reward Ratio: 1:{setup.rr:.2f}
    - Rule Confluences Found: {', '.join(setup.reasons)}

    Recent Price Context (M15 Last 5 Candles): {recent_m15_summary}
    Recent Price Context (H4 Last 5 Candles): {recent_h4_summary}

    Audit Task:
    1. Verify if the setup direction aligns cleanly with market context.
    2. Assess whether entry/stop placement provides logical room for market movement.
    3. Check for red flags (e.g., overextended entry, weak displacement, immediate structural barriers).
    4. Provide your decision to APPROVE or REJECT the setup.
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=AIEvaluation,
            temperature=0.2,
        ),
    )

    return response.parsed
