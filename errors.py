"""
errors.py
---------
Custom exception types so different kinds of failures can be told
apart and logged/handled differently, instead of everything just
being a generic Exception printed to the console.
"""


class APIError(Exception):
    """A TwelveData request failed for a reason that isn't a rate limit
    or malformed data (e.g. network error, unexpected error response)."""
    pass


class RateLimitError(APIError):
    """TwelveData told us we've hit a rate limit (HTTP 429 or an
    error response indicating too many requests)."""
    pass


class MalformedDataError(APIError):
    """TwelveData responded successfully, but the data was empty,
    missing fields, or otherwise not usable."""
    pass


class TelegramDeliveryError(Exception):
    """A Telegram message failed to send."""
    pass
