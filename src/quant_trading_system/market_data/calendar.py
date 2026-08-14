"""Exchange-local session construction with UTC storage."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from quant_trading_system.instruments import Exchange

from .domain import TradingSession

_ZONES = {
    Exchange.SSE: ZoneInfo("Asia/Shanghai"),
    Exchange.SZSE: ZoneInfo("Asia/Shanghai"),
    Exchange.BSE: ZoneInfo("Asia/Shanghai"),
    Exchange.HKEX: ZoneInfo("Asia/Hong_Kong"),
}
_HOURS = {
    Exchange.SSE: (time(9, 30), time(15, 0)),
    Exchange.SZSE: (time(9, 30), time(15, 0)),
    Exchange.BSE: (time(9, 30), time(15, 0)),
    Exchange.HKEX: (time(9, 30), time(16, 0)),
}


def make_session(exchange: Exchange, trading_date: date, *, is_open: bool = True) -> TradingSession:
    zone = _ZONES[exchange]
    opens, closes = _HOURS[exchange]
    return TradingSession(
        exchange=exchange.value,
        trading_date=trading_date,
        opens_at=datetime.combine(trading_date, opens, zone),
        closes_at=datetime.combine(trading_date, closes, zone),
        is_open=is_open,
    )
