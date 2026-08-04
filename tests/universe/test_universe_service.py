from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from quant_trading_system.universe import ApplyMembershipBatch, BatchStatus, StrategyUniverseKind, UniverseDefinition
from quant_trading_system.universe.errors import BatchConflict, BatchRejected, StaleUniverse, UniverseNotFound

NOW = datetime(2024, 1, 2, 8, tzinfo=timezone.utc)


def batch(pool, codes=("510300.SH",), batch_id="b1", effective=date(2024, 1, 2), available=NOW):
    return ApplyMembershipBatch(pool.universe_id, batch_id, effective, NOW, available, tuple(codes))


def test_apply_and_get_members(universe_setup):
    service, _, pool, _, etf, *_ = universe_setup
    service.apply_membership_batch(batch(pool))
    assert service.get_members(pool.universe_id, NOW)[0].instrument_id == etf.instrument_id


def test_available_boundary_is_inclusive(universe_setup):
    service, _, pool, *_ = universe_setup
    service.apply_membership_batch(batch(pool))
    assert len(service.get_members(pool.universe_id, NOW)) == 1


def test_before_available_is_invisible(universe_setup):
    service, _, pool, *_ = universe_setup
    service.apply_membership_batch(batch(pool))
    assert service.get_members(pool.universe_id, NOW - timedelta(microseconds=1)) == ()


def test_before_effective_date_is_inactive(universe_setup):
    service, _, pool, *_ = universe_setup
    service.apply_membership_batch(batch(pool, effective=date(2024, 1, 3)))
    assert service.get_members(pool.universe_id, NOW) == ()


def test_idempotent_batch(universe_setup):
    service, _, pool, *_ = universe_setup
    assert service.apply_membership_batch(batch(pool)).batch_id == service.apply_membership_batch(batch(pool)).batch_id


def test_idempotency_conflict(universe_setup):
    service, _, pool, *_ = universe_setup
    service.apply_membership_batch(batch(pool))
    with pytest.raises(BatchConflict): service.apply_membership_batch(batch(pool, codes=("510300.SH", "bad")))


@pytest.mark.parametrize("codes,code", [((), "EMPTY_UNIVERSE"), (("bad",), "UNRESOLVED_MEMBER"), (("510300.SH", "510300.SH"), "UNRESOLVED_MEMBER")])
def test_bad_batches_fail_closed(universe_setup, codes, code):
    service, repository, pool, *_ = universe_setup
    with pytest.raises(BatchRejected): service.apply_membership_batch(batch(pool, codes=codes))
    stored = repository.get_batch(pool.universe_id, "b1")
    assert stored.status is BatchStatus.REJECTED and repository.quality_results(stored.batch_id)[0].code == code


@pytest.mark.parametrize("pool_name,code", [("etf", "600000.SH"), ("equity", "510300.SH")])
def test_pool_asset_type_isolation(universe_setup, pool_name, code):
    service, _, etf_pool, equity_pool, *_ = universe_setup
    pool = etf_pool if pool_name == "etf" else equity_pool
    with pytest.raises(BatchRejected): service.apply_membership_batch(batch(pool, codes=(code,)))


def test_equity_pool_accepts_a_and_hk_connect(universe_setup):
    service, _, _, pool, _, stock, hk = universe_setup
    service.apply_membership_batch(batch(pool, codes=("600000.SH", "00005.HK")))
    assert {x.instrument_id for x in service.get_members(pool.universe_id, NOW)} == {stock.instrument_id, hk.instrument_id}


def test_full_batch_closes_removed_member(universe_setup):
    service, _, _, pool, _, stock, _ = universe_setup
    service.apply_membership_batch(batch(pool, codes=("600000.SH", "00005.HK")))
    later = NOW + timedelta(days=1)
    service.apply_membership_batch(batch(pool, codes=("600000.SH",), batch_id="b2", effective=date(2024,1,3), available=later))
    assert {x.instrument_id for x in service.get_members(pool.universe_id, later)} == {stock.instrument_id}


def test_same_effective_date_second_batch_rejected(universe_setup):
    service, _, pool, *_ = universe_setup
    service.apply_membership_batch(batch(pool))
    with pytest.raises(BatchRejected): service.apply_membership_batch(batch(pool, batch_id="b2"))


def test_change_ratio_gate(universe_setup):
    service, _, _, _, *_ = universe_setup
    pool = UniverseDefinition("strict", StrategyUniverseKind.GENERAL, "tushare", "1", "strict", Decimal("0"))
    service.create_definition(pool); service.apply_membership_batch(batch(pool))
    with pytest.raises(BatchRejected): service.apply_membership_batch(batch(pool, codes=("600000.SH",), batch_id="b2", effective=date(2024,1,3), available=NOW+timedelta(days=1)))


def test_explanation_reasons(universe_setup):
    service, _, pool, _, etf, *_ = universe_setup
    service.apply_membership_batch(batch(pool))
    assert service.explain_membership(pool.universe_id, etf.instrument_id, NOW).reason == "ELIGIBLE"
    assert service.explain_membership(pool.universe_id, uuid4(), NOW).reason == "NO_ACTIVE_MEMBERSHIP"


def test_explanation_not_yet_available(universe_setup):
    service, _, pool, _, etf, *_ = universe_setup
    service.apply_membership_batch(batch(pool, available=NOW+timedelta(days=1)))
    assert service.explain_membership(pool.universe_id, etf.instrument_id, NOW).reason == "NOT_YET_AVAILABLE"


def test_snapshot_is_immutable(universe_setup):
    service, repository, pool, *_ = universe_setup
    service.apply_membership_batch(batch(pool)); snapshot = service.freeze_snapshot(pool.universe_id, NOW, uuid4())
    assert repository.get_snapshot(snapshot.snapshot_id) == snapshot


def test_pool_identity_domains_snapshot_hash(universe_setup):
    service, _, etf_pool, equity_pool, *_ = universe_setup
    service.apply_membership_batch(batch(etf_pool)); service.apply_membership_batch(batch(equity_pool, codes=("600000.SH",)))
    data_id = uuid4(); left = service.freeze_snapshot(etf_pool.universe_id, NOW, data_id); right = service.freeze_snapshot(equity_pool.universe_id, NOW, data_id)
    assert left.snapshot_id != right.snapshot_id and left.member_hash != right.member_hash


def test_strategy_universe_staleness(universe_setup):
    service, _, pool, *_ = universe_setup; service.apply_membership_batch(batch(pool))
    with pytest.raises(StaleUniverse): service.get_strategy_universe(StrategyUniverseKind.ETF_TIMING_POOL, NOW+timedelta(days=11), uuid4())


def test_strategy_universe_fresh(universe_setup):
    service, _, pool, *_ = universe_setup; service.apply_membership_batch(batch(pool))
    assert service.get_strategy_universe(StrategyUniverseKind.ETF_TIMING_POOL, NOW, uuid4()).universe_id == pool.universe_id


def test_unknown_universe(universe_setup):
    service, *_ = universe_setup
    with pytest.raises(UniverseNotFound): service.get_members(uuid4(), NOW)
