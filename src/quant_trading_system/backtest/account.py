from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from .domain import BacktestPosition, BacktestSnapshot, LedgerKind, MarketRule, Side, SimFill, SimLedgerEntry
from .errors import SimulationInvariantError
from quant_trading_system.portfolio.ledger_kernel import calculate_fill_accounting


class SimulationAccount:
    def __init__(self, run_id: UUID, initial_cash: Decimal):
        self.run_id = run_id
        self.cash = Decimal(initial_cash)
        self.quantities: dict[UUID, int] = {}
        self.sellable: dict[UUID, int] = {}
        self.costs: dict[UUID, Decimal] = {}
        self.pending_settlement: list[tuple[datetime, UUID, int, UUID]] = []
        self.ledger: list[SimLedgerEntry] = []
        self.total_fees = Decimal()

    def settle(self, as_of: datetime) -> tuple[SimLedgerEntry, ...]:
        due = [item for item in self.pending_settlement if item[0] <= as_of]
        self.pending_settlement = [item for item in self.pending_settlement if item[0] > as_of]
        entries = []
        for effective_at, instrument_id, quantity, source_id in due:
            self.sellable[instrument_id] = self.sellable.get(instrument_id, 0) + quantity
            entry = SimLedgerEntry(self.run_id, LedgerKind.SETTLEMENT, effective_at, source_id, instrument_id=instrument_id, quantity_delta=quantity)
            self.ledger.append(entry)
            entries.append(entry)
        self._assert_nonnegative()
        return tuple(entries)

    def apply_fill(self, fill: SimFill, rule: MarketRule) -> tuple[SimLedgerEntry, ...]:
        current_quantity = self.quantities.get(fill.instrument_id, 0)
        current_cost = self.costs.get(fill.instrument_id, Decimal())
        if fill.side is Side.SELL and (
            current_quantity < fill.quantity
            or self.sellable.get(fill.instrument_id, 0) < fill.quantity
        ):
            raise SimulationInvariantError("insufficient simulated sellable position")
        delta = calculate_fill_accounting(
            side=fill.side, quantity=fill.quantity, price=fill.price,
            commission=fill.commission, tax=fill.tax, other_fee=fill.platform_fee,
            current_quantity=current_quantity, current_cost=current_cost,
        )
        total_fee = delta.fee
        if fill.side is Side.BUY:
            cash_delta = delta.cash_delta
            if self.cash + cash_delta < 0:
                raise SimulationInvariantError("insufficient simulated cash")
            quantity_delta = delta.quantity_delta
            self.quantities[fill.instrument_id] = self.quantities.get(fill.instrument_id, 0) + fill.quantity
            if rule.settlement_days == 0:
                self.sellable[fill.instrument_id] = self.sellable.get(fill.instrument_id, 0) + fill.quantity
            else:
                self.pending_settlement.append((fill.filled_at + timedelta(days=rule.settlement_days), fill.instrument_id, fill.quantity, fill.fill_id))
        else:
            cash_delta = delta.cash_delta
            quantity_delta = delta.quantity_delta
            self.quantities[fill.instrument_id] -= fill.quantity
            self.sellable[fill.instrument_id] -= fill.quantity
        self.costs[fill.instrument_id] = current_cost + delta.cost_delta
        self.cash += cash_delta
        self.total_fees += total_fee
        entries = [
            SimLedgerEntry(self.run_id, LedgerKind.CASH, fill.filled_at, fill.fill_id, cash_delta=cash_delta),
            SimLedgerEntry(self.run_id, LedgerKind.POSITION, fill.filled_at, fill.fill_id, instrument_id=fill.instrument_id, quantity_delta=quantity_delta),
            SimLedgerEntry(self.run_id, LedgerKind.FEE, fill.filled_at, fill.fill_id, fee_delta=total_fee),
        ]
        if fill.side is Side.BUY and rule.settlement_days == 0:
            entries.append(SimLedgerEntry(self.run_id, LedgerKind.SETTLEMENT, fill.filled_at, fill.fill_id, instrument_id=fill.instrument_id, quantity_delta=fill.quantity))
        elif fill.side is Side.SELL:
            entries.append(SimLedgerEntry(self.run_id, LedgerKind.SETTLEMENT, fill.filled_at, fill.fill_id, instrument_id=fill.instrument_id, quantity_delta=-fill.quantity))
        self.ledger.extend(entries)
        self._assert_nonnegative()
        return tuple(entries)

    def apply_cash_action(self, source_id: UUID, effective_at: datetime, amount: Decimal) -> SimLedgerEntry:
        if self.cash + amount < 0:
            raise SimulationInvariantError("corporate action makes cash negative")
        self.cash += amount
        entry = SimLedgerEntry(self.run_id, LedgerKind.CORPORATE_ACTION, effective_at, source_id, cash_delta=amount)
        self.ledger.append(entry)
        return entry

    def snapshot(self, as_of: datetime, prices: dict[UUID, Decimal], sleeve_exposure: dict[str, Decimal]) -> BacktestSnapshot:
        positions = tuple(
            BacktestPosition(instrument_id, quantity, self.sellable.get(instrument_id, 0), prices[instrument_id], prices[instrument_id] * quantity)
            for instrument_id, quantity in sorted(self.quantities.items(), key=lambda item: str(item[0]))
            if quantity and instrument_id in prices
        )
        if any(quantity and instrument_id not in prices for instrument_id, quantity in self.quantities.items()):
            raise SimulationInvariantError("missing valuation price")
        nav = self.cash + sum((position.market_value for position in positions), Decimal())
        payload = {"as_of": as_of.isoformat(), "cash": str(self.cash), "positions": [(str(p.instrument_id), p.quantity, p.sellable_quantity, str(p.market_price)) for p in positions]}
        content_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return BacktestSnapshot(self.run_id, as_of, self.cash, positions, nav, sleeve_exposure, content_hash)

    def _assert_nonnegative(self):
        if self.cash < 0 or any(value < 0 for value in self.quantities.values()) or any(value < 0 for value in self.sellable.values()) or any(value < 0 for value in self.costs.values()):
            raise SimulationInvariantError("negative simulated balance")
