from datetime import date
from decimal import Decimal

from quant_trading_system.instruments import (
    AliasInput,
    AssetType,
    Board,
    Exchange,
    InstrumentService,
    RegisterInstrumentCommand,
    TradingSpecInput,
)
from quant_trading_system.instruments.in_memory import InMemoryInstrumentRepository
from quant_trading_system.tdx_bridge.resolver import CachedInstrumentService


class CountingRepository(InMemoryInstrumentRepository):
    def __init__(self) -> None:
        super().__init__()
        self.alias_reads = 0
        self.instrument_reads = 0
        self.lifecycle_reads = 0

    def find_alias_overlaps(self, source, code, validity):
        self.alias_reads += 1
        return super().find_alias_overlaps(source, code, validity)

    def get_instrument(self, instrument_id):
        self.instrument_reads += 1
        return super().get_instrument(instrument_id)

    def get_lifecycle_periods(self, instrument_id):
        self.lifecycle_reads += 1
        return super().get_lifecycle_periods(instrument_id)


def test_resolver_reads_reference_data_once_for_many_dates() -> None:
    repository = CountingRepository()
    InstrumentService(repository).register(RegisterInstrumentCommand(
        source="tdx",
        source_record_id="600000.SH",
        revision="1",
        batch_id="test",
        asset_type=AssetType.A_SHARE,
        exchange=Exchange.SSE,
        board=Board.SH_MAIN,
        currency="CNY",
        name="浦发银行",
        list_date=date(1999, 11, 10),
        aliases=(AliasInput("tdx", "600000.SH", date(1999, 11, 10)),),
        trading_specs=(TradingSpecInput(date(1999, 11, 10), 100, Decimal("0.01"), 100),),
    ))
    repository.alias_reads = repository.instrument_reads = repository.lifecycle_reads = 0
    resolver = CachedInstrumentService(repository)

    assert resolver.resolve("tdx", "600000.SH", date(2005, 1, 4)).tradable
    assert resolver.resolve("tdx", "600000.SH", date(2026, 7, 28)).tradable
    assert repository.alias_reads == 1
    assert repository.instrument_reads == 1
    assert repository.lifecycle_reads == 1
