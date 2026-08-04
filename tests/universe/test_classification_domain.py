from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_trading_system.universe import ClassificationMembership, MembershipPeriod, StrategyUniverseKind, UniverseDefinition
from quant_trading_system.universe.errors import InvalidUniverse

NOW = datetime(2024, 1, 2, 8, tzinfo=timezone.utc)


@pytest.mark.parametrize("ratio", ["-0.1", "1.1"])
def test_definition_change_ratio_bounds(ratio):
    with pytest.raises(InvalidUniverse): UniverseDefinition("x", StrategyUniverseKind.GENERAL, "s", "1", "r", Decimal(ratio))


@pytest.mark.parametrize("days", [-1, -5])
def test_definition_staleness_nonnegative(days):
    with pytest.raises(InvalidUniverse): UniverseDefinition("x", StrategyUniverseKind.GENERAL, "s", "1", "r", max_staleness_days=days)


def make_class(instrument_id, provider="p", system="sys", version="1", level=1, code="10", start=date(2024,1,1), end=None, available=NOW):
    return ClassificationMembership(instrument_id, provider, system, version, level, code, "industry", start, end, available)


def test_two_classification_systems_do_not_mix(universe_setup):
    service, _, _, _, _, stock, _ = universe_setup
    service.add_classification(make_class(stock.instrument_id, provider="A")); service.add_classification(make_class(stock.instrument_id, provider="B"))
    assert len(service.get_classification(stock.instrument_id, NOW, provider="A", system="sys", version="1", level=1)) == 1


def test_classification_not_visible_early(universe_setup):
    service, _, _, _, _, stock, _ = universe_setup
    service.add_classification(make_class(stock.instrument_id, available=NOW+timedelta(days=1)))
    assert service.get_classification(stock.instrument_id, NOW, provider="p", system="sys", version="1", level=1) == ()


def test_classification_overlap_rejected(universe_setup):
    service, _, _, _, _, stock, _ = universe_setup
    service.add_classification(make_class(stock.instrument_id))
    with pytest.raises(InvalidUniverse): service.add_classification(make_class(stock.instrument_id, start=date(2024,2,1)))


@pytest.mark.parametrize("level", [0, -1])
def test_classification_level_positive(level):
    with pytest.raises(InvalidUniverse): make_class(uuid4(), level=level)


def test_membership_half_open_boundary():
    value = MembershipPeriod(uuid4(), uuid4(), date(2024,1,1), date(2024,2,1), NOW, NOW, "b")
    assert value.active(date(2024,1,31)) and not value.active(date(2024,2,1))


@pytest.mark.parametrize("delta", [0, -1])
def test_membership_end_must_follow_start(delta):
    with pytest.raises(InvalidUniverse): MembershipPeriod(uuid4(), uuid4(), date(2024,1,2), date(2024,1,2)+timedelta(days=delta), NOW, NOW, "b")


def test_membership_availability_order():
    with pytest.raises(InvalidUniverse): MembershipPeriod(uuid4(), uuid4(), date.today(), None, NOW, NOW-timedelta(seconds=1), "b")


@pytest.mark.parametrize("kind", list(StrategyUniverseKind))
def test_kind_roundtrip(kind): assert StrategyUniverseKind(kind.value) is kind

