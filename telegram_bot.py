"""
telegram_bot.py
---------------
Sends a message to your Telegram chat.

CHANGE IN THIS VERSION: a failed send now raises TelegramDeliveryError
instead of just printing an error and silently continuing. This lets
run_once.py know a signal wasn't actually delivered, so it can queue
it for a bounded, staleness-checked retry instead of losing it.
"""

import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from errors import TelegramDeliveryError


def send_message(text: str):
    """
    Sends a message. Raises TelegramDeliveryError if it fails for any
    reason (network error, bad token, Telegram API error, etc).
    Returns the response on success.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }

    try:
        response = requests.post(url, data=payload, timeout=10)
    except requests.RequestException as e:
        raise TelegramDeliveryError(f"Network error sending Telegram message: {e}")

    if response.status_code != 200:
        raise TelegramDeliveryError(f"Telegram send failed ({response.status_code}): {response.text}")

    return response


def try_send_message(text: str) -> bool:
    """
    Convenience wrapper for callers that just want a True/False result
    instead of handling the exception themselves.
    """
    try:
        send_message(text)
        return True
    except TelegramDeliveryError as e:
        print(f"Telegram delivery failed: {e}")
        return False
