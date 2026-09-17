"""
market_hours.py
----------------
A conservative approximation of when forex/gold markets are actually
open. This is NOT exact broker-specific hours (those vary slightly by
broker and holiday calendars) - it's a deliberately conservative
window that avoids evaluating clearly-dead weekend data.

WHY THIS MATTERS:
TwelveData can still return "candles" over the weekend (often just
flat, repeated, or stale prices since nothing is actually trading).
Without this check, the bot could generate signals off dead price
action that has no real market behind it.

THE WINDOW (all times UTC):
- Closed all day Saturday
- Closed Sunday before markets reopen (~22:00 UTC, roughly Sydney open)
- Closed Friday from ~21:00 UTC onward (roughly NY close)

This intentionally errs on the side of "skip more than necessary"
rather than "risk evaluating dead data" - a few extra quiet hours on
Friday evening/Sunday are a small cost compared to a false signal.
"""

from datetime import datetime

from config import FRIDAY_CLOSE_HOUR_UTC, SUNDAY_OPEN_HOUR_UTC, ENFORCE_MARKET_HOURS


def is_market_closed(now_utc: datetime) -> bool:
    if not ENFORCE_MARKET_HOURS:
        return False

    weekday = now_utc.weekday()  # Monday=0 ... Sunday=6
    hour = now_utc.hour

    if weekday == 5:  # Saturday - closed all day
        return True
    if weekday == 6 and hour < SUNDAY_OPEN_HOUR_UTC:  # Sunday before reopen
        return True
    if weekday == 4 and hour >= FRIDAY_CLOSE_HOUR_UTC:  # Friday after close
        return True

    return False
