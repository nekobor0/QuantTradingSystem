"""Configuration and dated cost rules for the local paper account."""

from __future__ import annotations

from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
STATE_FILE = BASE_DIR / "state.json"

TRADING_MODE = "paper"
ALLOW_LIVE_TRADING = False
ENABLE_ORDER_SUBMISSION = False

PRINCIPAL = 1_000_000.0
DIV_WEIGHT = 0.75
VOL_WEIGHT = 0.25
DIV_CAPITAL = PRINCIPAL * DIV_WEIGHT
VOL_CAPITAL = PRINCIPAL * VOL_WEIGHT

YIELD_THRESHOLD = 0.05
TOP_N = 100
FACTOR_WEIGHTS = {"ep": 0.4, "amihud": 0.3, "div_yield": 0.3}
TARGET_VOL = 0.20
VOL_WINDOW = 60
MA_N = 250
MIN_LISTED_DAYS = 180
MIN_ADV_CNY = 1_000_000.0
BUY_LOT = 100

COMMISSION_RATE = 0.00012
# Conservative default. Confirm the account contract before live use.
MIN_COMMISSION_CNY = 5.0

RISK_ALERT_DRAWDOWN = -0.20
RISK_HARD_DRAWDOWN = -0.25
RISK_HARD_ACTION = "VOL_TO_CASH"

BENCHMARKS = {"上证指数": "000001.SH", "沪深300": "000300.SH"}


def commission(notional: float) -> float:
    """Broker commission for one order."""
    if notional <= 0:
        return 0.0
    return max(notional * COMMISSION_RATE, MIN_COMMISSION_CNY)


def stamp_duty_rate(trade_date: str | date) -> float:
    """A-share sell stamp duty with the 2023-08-28 rate change."""
    d = date.fromisoformat(trade_date) if isinstance(trade_date, str) else trade_date
    return 0.0005 if d >= date(2023, 8, 28) else 0.001


def dividend_tax_rate(holding_days: int) -> float:
    """Deferred dividend tax rate applied when a lot is sold."""
    if holding_days <= 30:
        return 0.20
    if holding_days <= 365:
        return 0.10
    return 0.0
