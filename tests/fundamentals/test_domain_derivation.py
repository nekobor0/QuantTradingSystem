from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_trading_system.fundamentals import (
    FundamentalFact, MetricDefinition, PeriodType, QueryPolicy, ShareCapitalChange,
    SourceMapping, ValueKind, quarters_to_ttm, ytd_to_quarter,
)
from quant_trading_system.fundamentals.errors import DerivationUnavailable, InvalidFundamental

NOW = datetime(2024, 4, 30, tzinfo=timezone.utc)


def fact(period_end, period_type=PeriodType.YTD, value=Decimal("10"), instrument_id=None, metric_id=None):
    return FundamentalFact(uuid4(), instrument_id or uuid4(), metric_id or uuid4(), period_end,
        period_type, "source", "1", value, "CNY", "CNY", None)


@pytest.mark.parametrize("month,current,previous,expected", [(3,"10",None,"10"),(6,"25","10","15"),(9,"40","25","15"),(12,"60","40","20")])
def test_ytd_to_quarter_golden(month, current, previous, expected):
    current_fact = fact(date(2024, month, 30 if month in (6,9) else 31), value=Decimal(current))
    previous_month = month - 3
    previous_day = 30 if previous_month in (6, 9) else 31
    previous_fact = None if previous is None else fact(date(2024, previous_month, previous_day), value=Decimal(previous), instrument_id=current_fact.instrument_id, metric_id=current_fact.metric_id)
    assert ytd_to_quarter(current_fact, previous_fact).value == Decimal(expected)


@pytest.mark.parametrize("mutation", ["null", "wrong_type", "missing_previous", "different_metric", "different_year"])
def test_ytd_derivation_rejects_invalid_inputs(mutation):
    current = fact(date(2024, 6, 30), value=Decimal("20"))
    previous = fact(date(2024, 3, 31), value=Decimal("10"), instrument_id=current.instrument_id, metric_id=current.metric_id)
    if mutation == "null": current = replace(current, value=None)
    elif mutation == "wrong_type": current = replace(current, period_type=PeriodType.QUARTER)
    elif mutation == "missing_previous": previous = None
    elif mutation == "different_metric": previous = replace(previous, metric_id=uuid4())
    else: previous = replace(previous, period_end=date(2023, 12, 31))
    with pytest.raises(DerivationUnavailable): ytd_to_quarter(current, previous)


def four_quarters(gap=False):
    instrument_id, metric_id = uuid4(), uuid4()
    months = [3,6,9,12] if not gap else [3,6,10,12]
    return [fact(date(2024,m,30 if m in (6,9) else 31), PeriodType.QUARTER, Decimal(i), instrument_id, metric_id) for i,m in enumerate(months,1)]


def test_ttm_golden_sum_and_lineage():
    result = quarters_to_ttm(four_quarters())
    assert result.value == Decimal("10") and len(result.lineage) == 4


@pytest.mark.parametrize("mutation", ["missing", "gap", "null", "wrong_type", "instrument", "metric"])
def test_ttm_rejects_incomplete_or_mixed(mutation):
    values = four_quarters()
    if mutation == "missing": values.pop()
    elif mutation == "gap": values = four_quarters(True)
    elif mutation == "null": values[0] = replace(values[0], value=None)
    elif mutation == "wrong_type": values[0] = replace(values[0], period_type=PeriodType.YTD)
    elif mutation == "instrument": values[0] = replace(values[0], instrument_id=uuid4())
    else: values[0] = replace(values[0], metric_id=uuid4())
    with pytest.raises(DerivationUnavailable): quarters_to_ttm(values)


@pytest.mark.parametrize("name,unit", [("", "CNY"), ("revenue", "")])
def test_metric_requires_text(name, unit):
    with pytest.raises(InvalidFundamental): MetricDefinition(name, unit, ValueKind.AMOUNT, True)


@pytest.mark.parametrize("scale", ["0", "-1"])
def test_mapping_scale_positive(scale):
    with pytest.raises(InvalidFundamental): SourceMapping("source", "field", uuid4(), "unit", Decimal(scale))


@pytest.mark.parametrize("total,float_shares", [("0","0"),("10","-1"),("10","11")])
def test_share_capital_rules(total, float_shares):
    with pytest.raises(InvalidFundamental): ShareCapitalChange(uuid4(), date.today(), Decimal(total), Decimal(float_shares), "s", NOW, NOW)


def test_share_availability_order():
    with pytest.raises(InvalidFundamental): ShareCapitalChange(uuid4(), date.today(), Decimal("10"), Decimal("5"), "s", NOW, NOW-timedelta(seconds=1))


@pytest.mark.parametrize("kind", list(ValueKind))
def test_value_kind_roundtrip(kind): assert ValueKind(kind.value) is kind


@pytest.mark.parametrize("period", list(PeriodType))
def test_period_type_roundtrip(period): assert PeriodType(period.value) is period


@pytest.mark.parametrize("policy", list(QueryPolicy))
def test_query_policy_roundtrip(policy): assert QueryPolicy(policy.value) is policy
