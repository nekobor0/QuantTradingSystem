from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, cast
from uuid import UUID

from .errors import ValidationError


@dataclass(frozen=True, slots=True)
class RecommendationView:
    recommendation_id: UUID
    instrument_id: UUID
    side: str
    quantity: int
    version: int
    source_label: str = "COMBINED_NET"


@dataclass(frozen=True, slots=True)
class DailyDecisionView:
    as_of: datetime
    mode: str
    hard_block: bool
    blocking_reasons: tuple[str, ...]
    etf: Mapping[str, object]
    equity: Mapping[str, object]
    sleeve_contributions: tuple[Mapping[str, object], ...]
    recommendations: tuple[RecommendationView, ...]
    approval_enabled: bool


def build_daily_decision_view(payload: Mapping[str, object]) -> DailyDecisionView:
    try:
        as_of = datetime.fromisoformat(str(payload["as_of"])); mode = str(payload["mode"]); hard = bool(payload.get("hard_block", False))
        reasons = tuple(str(x) for x in cast(list[object], payload.get("blocking_reasons", [])))
        etf = dict(cast(Mapping[str, object], payload["etf"])); equity = dict(cast(Mapping[str, object], payload["equity"]))
        contributions = tuple(dict(x) for x in cast(list[Mapping[str, object]], payload.get("sleeve_contributions", [])))
        rows = tuple(RecommendationView(UUID(str(x["recommendation_id"])), UUID(str(x["instrument_id"])), str(x["side"]), int(cast(int, x["quantity"])), int(cast(int, x["version"]))) for x in cast(list[Mapping[str, object]], payload.get("net_recommendations", [])))
    except (KeyError, TypeError, ValueError) as error:
        raise ValidationError("invalid daily decision payload") from error
    if as_of.tzinfo is None or as_of.utcoffset() is None: raise ValidationError("daily decision as_of must be timezone-aware")
    if mode not in ("LIVE", "PAPER", "BACKTEST"): raise ValidationError("mode label required")
    if len({x.instrument_id for x in rows}) != len(rows): raise ValidationError("only one combined net recommendation per instrument")
    if any(x.get("order_action") for x in contributions): raise ValidationError("sleeve contribution cannot expose order action")
    return DailyDecisionView(as_of, mode, hard, reasons, etf, equity, contributions, rows, not hard)
