from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from quant_trading_system.instruments import (
    AliasInput,
    ChangeAliasCommand,
    ChangeLifecycleCommand,
    ChangeTradingSpecCommand,
    InstrumentService,
    LifecycleStatus,
    TradingSpecInput,
)
from quant_trading_system.instruments.errors import (
    InstrumentNotFound,
    InvalidInstrument,
    InvalidLifecycleTransition,
    SourceRecordConflict,
    TradingSpecNotFound,
    ValidityOverlap,
)


def test_three_explicit_aliases_resolve_to_same_instrument(repository, listed_command) -> None:
    service = InstrumentService(repository)
    instrument = service.register(listed_command())
    resolved_ids = {
        service.resolve("TUSHARE", code, date(2020, 1, 2)).instrument.instrument_id
        for code in ("600000.SH", "sh.600000", "600000")
    }
    assert resolved_ids == {instrument.instrument_id}


def test_resolve_unknown_alias_uses_stable_error(repository) -> None:
    with pytest.raises(InstrumentNotFound) as caught:
        InstrumentService(repository).resolve("tushare", "missing", date(2020, 1, 1))
    assert caught.value.code == "INSTRUMENT_NOT_FOUND"


def test_listing_date_boundaries_control_tradability(repository, listed_command) -> None:
    service = InstrumentService(repository)
    instrument = service.register(listed_command())
    with pytest.raises(InstrumentNotFound):
        service.resolve("tushare", "600000.SH", date(2020, 1, 1))
    assert not service.is_tradable(instrument.instrument_id, date(2020, 1, 1))
    assert service.is_tradable(instrument.instrument_id, date(2020, 1, 2))


def test_registration_is_idempotent(repository, listed_command) -> None:
    service = InstrumentService(repository)
    first = service.register(listed_command())
    second = service.register(listed_command())
    assert second.instrument_id == first.instrument_id
    assert service.repository.resolve_aliases("tushare", "600000.SH", date(2020, 1, 2))[0].instrument_id == first.instrument_id


def test_source_revision_can_change_name_without_changing_id(repository, listed_command) -> None:
    service = InstrumentService(repository)
    original = service.register(listed_command())
    revised_command = listed_command(
        revision="2",
        name="浦发银行股份有限公司",
        instrument_id=original.instrument_id,
    )
    revised = service.register(revised_command)
    resolved = service.resolve("tushare", "600000.SH", date(2020, 1, 2))
    assert revised.instrument_id == original.instrument_id
    assert resolved.instrument.name == "浦发银行股份有限公司"


def test_source_revision_cannot_change_canonical_identity(repository, listed_command) -> None:
    service = InstrumentService(repository)
    original = service.register(listed_command())
    with pytest.raises(SourceRecordConflict):
        service.register(
            listed_command(
                revision="2",
                currency="HKD",
                instrument_id=original.instrument_id,
            )
        )
    assert repository.get_source_record("tushare", "600000.SH", "2") is None


def test_same_idempotency_key_with_different_content_fails(repository, listed_command) -> None:
    service = InstrumentService(repository)
    command = listed_command()
    service.register(command)
    with pytest.raises(SourceRecordConflict) as caught:
        service.register(replace(command, name="Different Name"))
    assert caught.value.code == "SOURCE_RECORD_CONFLICT"


def test_overlapping_aliases_in_one_command_fail_before_write(repository, listed_command) -> None:
    service = InstrumentService(repository)
    command = listed_command(
        aliases=(
            AliasInput("tushare", "600000.SH", date(2020, 1, 2)),
            AliasInput("tushare", "600000.SH", date(2021, 1, 1)),
        )
    )
    with pytest.raises(ValidityOverlap):
        service.register(command)
    assert repository.get_source_record("tushare", command.source_record_id, command.revision) is None


def test_alias_collision_with_existing_instrument_is_rejected(repository, listed_command) -> None:
    service = InstrumentService(repository)
    service.register(listed_command())
    second = listed_command(source_record_id="other", name="Other")
    with pytest.raises(ValidityOverlap):
        service.register(second)
    assert repository.get_source_record("tushare", "other", "1") is None


def test_trading_spec_uses_half_open_boundary(repository, listed_command) -> None:
    service = InstrumentService(repository)
    instrument = service.register(
        listed_command(
            trading_specs=(
                TradingSpecInput(date(2020, 1, 2), 100, "0.01", 100, 1000, date(2021, 1, 1)),
                TradingSpecInput(date(2021, 1, 1), 200, "0.01", 200, 2000),
            )
        )
    )
    assert service.get_trading_spec(instrument.instrument_id, date(2020, 12, 31)).lot_size == 100
    assert service.get_trading_spec(instrument.instrument_id, date(2021, 1, 1)).lot_size == 200


def test_missing_trading_spec_is_explicit(repository, listed_command) -> None:
    service = InstrumentService(repository)
    instrument = service.register(
        listed_command(
            trading_specs=(TradingSpecInput(date(2020, 1, 2), 100, "0.01", 100, valid_to=date(2020, 2, 1)),)
        )
    )
    with pytest.raises(TradingSpecNotFound):
        service.get_trading_spec(instrument.instrument_id, date(2020, 2, 1))


def test_candidate_can_transition_to_listed_on_list_date(repository, listed_command) -> None:
    service = InstrumentService(repository)
    command = listed_command(
        initial_status=LifecycleStatus.CANDIDATE,
        status_effective_from=date(2019, 12, 1),
    )
    instrument = service.register(command)
    assert not service.is_tradable(instrument.instrument_id, date(2019, 12, 31))
    listed = service.change_lifecycle(
        ChangeLifecycleCommand(instrument.instrument_id, LifecycleStatus.LISTED, date(2020, 1, 2), "IPO")
    )
    assert listed.lifecycle_status is LifecycleStatus.LISTED
    assert service.is_tradable(instrument.instrument_id, date(2020, 1, 2))


def test_candidate_cannot_skip_to_delisted(repository, listed_command) -> None:
    service = InstrumentService(repository)
    instrument = service.register(
        listed_command(initial_status=LifecycleStatus.CANDIDATE, status_effective_from=date(2019, 12, 1))
    )
    with pytest.raises(InvalidLifecycleTransition):
        service.change_lifecycle(
            ChangeLifecycleCommand(instrument.instrument_id, LifecycleStatus.DELISTED, date(2020, 1, 2), "bad")
        )


def test_listed_instrument_can_delist_and_remain_resolvable(repository, listed_command) -> None:
    service = InstrumentService(repository)
    instrument = service.register(listed_command())
    service.change_lifecycle(
        ChangeLifecycleCommand(instrument.instrument_id, LifecycleStatus.DELISTED, date(2021, 1, 1), "delisted")
    )
    assert service.resolve("tushare", "600000.SH", date(2021, 1, 1)).instrument.instrument_id == instrument.instrument_id
    assert not service.is_tradable(instrument.instrument_id, date(2021, 1, 1))


def test_code_change_closes_old_alias_without_changing_id(repository, listed_command) -> None:
    service = InstrumentService(repository)
    instrument = service.register(listed_command())
    service.change_alias(
        ChangeAliasCommand(
            instrument.instrument_id,
            "tushare",
            "600000.SH",
            "600000.NEW",
            date(2021, 1, 1),
            "vendor code migration",
        )
    )
    assert service.resolve("tushare", "600000.SH", date(2020, 12, 31)).instrument.instrument_id == instrument.instrument_id
    with pytest.raises(InstrumentNotFound):
        service.resolve("tushare", "600000.SH", date(2021, 1, 1))
    assert service.resolve("tushare", "600000.NEW", date(2021, 1, 1)).instrument.instrument_id == instrument.instrument_id


def test_code_change_rejects_an_alias_already_in_use(repository, listed_command) -> None:
    service = InstrumentService(repository)
    instrument = service.register(listed_command())
    with pytest.raises(ValidityOverlap):
        service.change_alias(
            ChangeAliasCommand(
                instrument.instrument_id,
                "tushare",
                "600000.SH",
                "600000",
                date(2021, 1, 1),
                "conflict",
            )
        )


def test_trading_spec_change_preserves_half_open_history(repository, listed_command) -> None:
    service = InstrumentService(repository)
    instrument = service.register(listed_command())
    service.change_trading_spec(
        ChangeTradingSpecCommand(
            instrument.instrument_id,
            date(2021, 1, 1),
            200,
            "0.02",
            200,
            2_000_000,
            "exchange rule change",
        )
    )
    old = service.get_trading_spec(instrument.instrument_id, date(2020, 12, 31))
    new = service.get_trading_spec(instrument.instrument_id, date(2021, 1, 1))
    assert (old.lot_size, old.tick_size) == (100, Decimal("0.01"))
    assert (new.lot_size, new.tick_size) == (200, Decimal("0.02"))


def test_historical_delisted_registration_preserves_history(repository, listed_command) -> None:
    service = InstrumentService(repository)
    instrument = service.register(
        listed_command(
            initial_status=LifecycleStatus.DELISTED,
            delist_date=date(2021, 1, 1),
            status_effective_from=date(2021, 1, 1),
        )
    )
    assert service.is_tradable(instrument.instrument_id, date(2020, 6, 1))
    assert not service.is_tradable(instrument.instrument_id, date(2021, 1, 1))


@pytest.mark.parametrize("field", ["aliases", "trading_specs"])
def test_registration_requires_alias_and_trading_spec(repository, listed_command, field) -> None:
    service = InstrumentService(repository)
    with pytest.raises(InvalidInstrument):
        service.register(listed_command(**{field: ()}))
