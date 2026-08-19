"""Paper-only portfolio runner. No broker connectivity is provided."""

from .config import ALLOW_LIVE_TRADING, ENABLE_ORDER_SUBMISSION, TRADING_MODE

assert TRADING_MODE == "paper"
assert ALLOW_LIVE_TRADING is False
assert ENABLE_ORDER_SUBMISSION is False

