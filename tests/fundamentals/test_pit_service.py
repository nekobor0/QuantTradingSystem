from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from quant_trading_system.fundamentals import FactInput, IngestFilingCommand, MetricDefinition, PeriodType, QueryPolicy, ShareCapitalChange, SourceMapping, SourcePriorityPolicy, ValueKind
from quant_trading_system.fundamentals.errors import FactNotFound, FilingConflict, IngestionRejected

NOW = datetime(2024, 4, 30, 8, tzinfo=timezone.utc)


def command(**overrides):
    values = dict(
        source="tushare", source_filing_id="filing-1", revision="1",
        source_code="600000.SH", report_type="Q1", period_end=date(2024, 3, 31),
        announced_at=NOW, available_at=NOW, ingested_at=NOW,
        raw_uri="file:///filing.parquet",
        facts=(FactInput("revenue", date(2024, 3, 31), PeriodType.YTD, "2", "万元", "CNY"),),
    )
    values.update(overrides)
    return IngestFilingCommand(**values)


def test_ingest_scales_amount(fundamentals_setup):
    service, instrument, metric, _ = fundamentals_setup
    service.ingest(command())
    assert service.get_latest_known_fact(instrument.instrument_id, metric.metric_id, NOW).value == Decimal("20000")


def test_fact_invisible_before_available_at(fundamentals_setup):
    service, instrument, metric, _ = fundamentals_setup
    service.ingest(command())
    with pytest.raises(FactNotFound):
        service.get_latest_known_fact(instrument.instrument_id, metric.metric_id, NOW - timedelta(microseconds=1))


def test_fact_visible_at_available_boundary(fundamentals_setup):
    service, instrument, metric, _ = fundamentals_setup
    service.ingest(command())
    assert service.get_latest_known_fact(instrument.instrument_id, metric.metric_id, NOW).revision == "1"


def test_same_payload_is_idempotent(fundamentals_setup):
    service, *_ = fundamentals_setup
    assert service.ingest(command()).filing_id == service.ingest(command()).filing_id


def test_same_key_changed_payload_conflicts(fundamentals_setup):
    service, *_ = fundamentals_setup
    service.ingest(command())
    with pytest.raises(FilingConflict):
        service.ingest(command(report_type="changed"))


@pytest.mark.parametrize("field", ["announced_at", "available_at"])
def test_missing_visibility_time_rejected(fundamentals_setup, field):
    service, *_ = fundamentals_setup
    with pytest.raises(IngestionRejected):
        service.ingest(command(**{field: None}))


def test_inverted_visibility_time_rejected(fundamentals_setup):
    service, *_ = fundamentals_setup
    with pytest.raises(IngestionRejected):
        service.ingest(command(available_at=NOW - timedelta(seconds=1)))


@pytest.mark.parametrize(
    "source_field,source_unit,code",
    [("unknown", "万元", "UNKNOWN_METRIC"), ("revenue", "元", "UNIT_MISMATCH")],
)
def test_mapping_quality_failures_are_recorded(fundamentals_setup, source_field, source_unit, code):
    service, _, _, repository = fundamentals_setup
    fact = FactInput(source_field, date(2024, 3, 31), PeriodType.YTD, "1", source_unit)
    with pytest.raises(IngestionRejected):
        service.ingest(command(facts=(fact,)))
    assert repository.quality_results(("tushare", "filing-1", "1"))[0].code == code


def test_null_remains_null(fundamentals_setup):
    service, instrument, metric, _ = fundamentals_setup
    fact = FactInput("revenue", date(2024, 3, 31), PeriodType.YTD, None, "万元")
    service.ingest(command(facts=(fact,)))
    assert service.get_latest_known_fact(instrument.instrument_id, metric.metric_id, NOW).value is None


def test_revision_does_not_rewrite_history(fundamentals_setup):
    service, instrument, metric, _ = fundamentals_setup
    service.ingest(command())
    later = datetime(2024, 5, 10, tzinfo=timezone.utc)
    revised = FactInput("revenue", date(2024, 3, 31), PeriodType.YTD, "3", "万元")
    service.ingest(command(revision="2", available_at=later, ingested_at=later, facts=(revised,)))
    assert service.get_latest_known_fact(instrument.instrument_id, metric.metric_id, NOW).revision == "1"
    assert service.get_latest_known_fact(instrument.instrument_id, metric.metric_id, later).revision == "2"


def test_revision_event_references_old_revision(fundamentals_setup):
    service, _, _, repository = fundamentals_setup
    service.ingest(command())
    service.ingest(command(revision="2"))
    assert repository.latest_event().old_revision == "1"


@pytest.mark.parametrize("raw,expected", [("1", "10000"), ("1.25", "12500"), ("-2", "-20000"), ("0", "0")])
def test_amount_scaling_cases(fundamentals_setup, raw, expected):
    service, instrument, metric, _ = fundamentals_setup
    fact = FactInput("revenue", date(2024, 3, 31), PeriodType.YTD, raw, "万元")
    service.ingest(command(facts=(fact,)))
    assert service.get_latest_known_fact(instrument.instrument_id, metric.metric_id, NOW).value == Decimal(expected)


def test_invalid_numeric_value_rejected(fundamentals_setup):
    service, *_ = fundamentals_setup
    fact = FactInput("revenue", date(2024, 3, 31), PeriodType.YTD, "not-a-number", "万元")
    with pytest.raises(IngestionRejected):
        service.ingest(command(facts=(fact,)))


def test_percent_is_stored_as_decimal(fundamentals_setup):
    service, instrument, _, _ = fundamentals_setup
    metric = MetricDefinition("roe", "ratio", ValueKind.PERCENT, False)
    service.define_metric(metric, (SourceMapping("tushare", "roe", metric.metric_id, "%"),))
    item = FactInput("roe", date(2024, 3, 31), PeriodType.QUARTER, "12.5", "%")
    service.ingest(command(facts=(item,)))
    assert service.get_latest_known_fact(instrument.instrument_id, metric.metric_id, NOW).value == Decimal("0.125")


def test_source_priority_requires_explicit_sources(fundamentals_setup):
    service, instrument, metric, _ = fundamentals_setup
    service.ingest(command())
    with pytest.raises(Exception):
        service.get_facts((instrument.instrument_id,), (metric.metric_id,), NOW, QueryPolicy.SOURCE_PRIORITY)


def test_share_capital_is_point_in_time(fundamentals_setup):
    service, instrument, _, _ = fundamentals_setup
    old = ShareCapitalChange(instrument.instrument_id, date(2024, 1, 1), Decimal("100"), Decimal("80"), "tushare", NOW, NOW)
    later_at = NOW + timedelta(days=10)
    revised = ShareCapitalChange(instrument.instrument_id, date(2024, 1, 1), Decimal("120"), Decimal("90"), "vendor2", later_at, later_at)
    service.record_share_change(old); service.record_share_change(revised)
    assert service.get_share_capital(instrument.instrument_id, date(2024, 2, 1), NOW).total_shares == 100
    assert service.get_share_capital(instrument.instrument_id, date(2024, 2, 1), later_at).total_shares == 120
