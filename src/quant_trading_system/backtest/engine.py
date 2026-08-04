from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Mapping
from uuid import UUID, uuid4

from quant_trading_system.strategies import CandidateAction, StrategyKind

from .account import SimulationAccount
from .broker import BrokerSimulator
from .context import PointInTimeValue, StrategyContext
from .domain import *
from .errors import InvalidBacktest, RunConflict, RunNotFound
from .metrics import calculate_metrics
from .ports import BacktestRepository

StrategyCallback = Callable[[StrategyContext, UUID], tuple[StrategyTarget, ...]]


class EventDrivenBacktestEngine:
    def __init__(self, repository: BacktestRepository):
        self.repository = repository
        self.broker = BrokerSimulator()

    def run(
        self,
        definition: BacktestDefinition,
        callbacks: Mapping[StrategyKind, StrategyCallback],
        bars: tuple[SimulationBar, ...],
        market_rules: tuple[MarketRule, ...],
        cost_rules: tuple[CostRule, ...],
        values: tuple[PointInTimeValue, ...] = (),
        corporate_actions: tuple[CorporateCashAction, ...] = (),
    ) -> BacktestResult:
        input_hash = self._hash(self._input_payload(definition, bars, market_rules, cost_rules, values, corporate_actions))
        existing = self.repository.find_run(input_hash)
        if existing is not None:
            existing_result = self.repository.get_result(existing.run_id)
            if existing_result is None:
                raise RunConflict("same input is already running or failed")
            return existing_result
        if set(callbacks) != {StrategyKind.ETF_TIMING, StrategyKind.EQUITY_DAILY_SELECTION}:
            raise InvalidBacktest("callbacks must contain exactly both first-batch strategies")
        now = datetime.now(timezone.utc)
        run = BacktestRun(definition.definition_id, input_hash, None, BacktestRunStatus.CREATED)
        run = run.transition(BacktestRunStatus.VALIDATING, now)
        self.repository.save_started(definition, run)
        try:
            self._validate_inputs(definition, bars, market_rules, cost_rules, corporate_actions)
            run = run.transition(BacktestRunStatus.RUNNING, now)
            self.repository.save_started(definition, run)
            completed_result = self._simulate(definition, run, callbacks, bars, market_rules, cost_rules, values, corporate_actions)
            self.repository.save_result(completed_result)
            return completed_result
        except Exception as error:
            failed = run.transition(BacktestRunStatus.FAILED, datetime.now(timezone.utc), f"{type(error).__name__}: {error}")
            self.repository.save_failed(failed)
            raise

    def get_result(self, run_id: UUID) -> BacktestResult:
        value = self.repository.get_result(run_id)
        if value is None:
            raise RunNotFound(str(run_id))
        return value

    def sensitivity(self, definition: BacktestDefinition, *, cost_multiplier: Decimal = Decimal("1"), extra_delay_bars: int = 0, participation_multiplier: Decimal = Decimal("1")) -> BacktestDefinition:
        if cost_multiplier <= 0 or extra_delay_bars < 0 or participation_multiplier <= 0:
            raise InvalidBacktest("invalid sensitivity")
        participation = min(Decimal("1"), definition.max_participation * participation_multiplier)
        return replace(definition, definition_id=uuid4(), name=definition.name + f" [cost={cost_multiplier},delay={extra_delay_bars},capacity={participation_multiplier}]", execution_delay_bars=definition.execution_delay_bars + extra_delay_bars, max_participation=participation)

    @staticmethod
    def scale_cost_rules(rules: tuple[CostRule, ...], multiplier: Decimal) -> tuple[CostRule, ...]:
        if multiplier <= 0:
            raise InvalidBacktest("cost multiplier must be positive")
        return tuple(replace(rule, cost_rule_id=uuid4(), commission_rate=rule.commission_rate * multiplier, minimum_commission=rule.minimum_commission * multiplier, sell_tax_rate=rule.sell_tax_rate * multiplier, platform_fee_rate=rule.platform_fee_rate * multiplier, slippage_rate=rule.slippage_rate * multiplier) for rule in rules)

    def _simulate(self, definition, run, callbacks, bars, market_rules, cost_rules, values, corporate_actions):
        ordered_bars = tuple(sorted(bars, key=lambda bar: (bar.market_time, str(bar.instrument_id), str(bar.bar_id))))
        by_time: dict[datetime, list[SimulationBar]] = {}
        for bar in ordered_bars:
            by_time.setdefault(bar.market_time, []).append(bar)
        account = SimulationAccount(run.run_id, definition.initial_cash)
        events: list[SimulationEvent] = []
        orders: list[SimOrder] = []
        fills: list[SimFill] = []
        snapshots: list[BacktestSnapshot] = []
        contributions: list[SleeveContribution] = []
        latest_prices: dict[UUID, Decimal] = {}
        sleeve_targets: dict[StrategyKind, dict[UUID, Decimal]] = {kind: {} for kind in callbacks}
        strategy_run_ids: dict[StrategyKind, UUID] = {kind: uuid4() for kind in callbacks}
        sequence = 0
        bar_sequence = 0

        def emit(at, priority, event_type, payload, causation_id=None):
            nonlocal sequence
            sequence += 1
            event = SimulationEvent(run.run_id, sequence, at, datetime.now(timezone.utc), priority, event_type, "1", payload, causation_id, run.run_id)
            events.append(event)
            return event

        pending_actions = list(sorted(corporate_actions, key=lambda item: (item.effective_at, str(item.action_id))))
        all_bars = ordered_bars
        for market_time, current_bars in sorted(by_time.items()):
            settlement_entries = account.settle(market_time)
            for entry in settlement_entries:
                emit(market_time, EventPriority.CORPORATE_ACTION_SETTLEMENT, "SettlementApplied", {"entry_id": str(entry.entry_id)})
            due_actions = [item for item in pending_actions if item.effective_at <= market_time]
            pending_actions = [item for item in pending_actions if item.effective_at > market_time]
            for action in due_actions:
                quantity = account.quantities.get(action.instrument_id, 0)
                account.apply_cash_action(action.action_id, action.effective_at, action.amount_per_share * quantity)
                emit(action.effective_at, EventPriority.CORPORATE_ACTION_SETTLEMENT, "CorporateActionApplied", {"instrument_id": str(action.instrument_id), "quantity": str(quantity)})
            for bar in current_bars:
                bar_sequence += 1
                latest_prices[bar.instrument_id] = bar.close
                emit(bar.market_time, EventPriority.MARKET_BAR, "MarketBarReceived", {"bar_id": str(bar.bar_id), "instrument_id": str(bar.instrument_id), "bar_sequence": str(bar_sequence)})

            context = StrategyContext(market_time, all_bars, values)
            emitted_targets: list[StrategyTarget] = []
            for kind in (StrategyKind.ETF_TIMING, StrategyKind.EQUITY_DAILY_SELECTION):
                targets = callbacks[kind](context, strategy_run_ids[kind])
                if any(target.kind is not kind or target.strategy_run_id != strategy_run_ids[kind] or target.decision_at != market_time for target in targets):
                    raise InvalidBacktest("strategy callback returned mismatched target provenance")
                for target in targets:
                    sleeve_targets[kind][target.instrument_id] = Decimal() if target.action is CandidateAction.EXIT else target.target_weight
                    emitted_targets.append(target)
                    emit(market_time, EventPriority.STRATEGY_DECISION, "StrategyTargetProduced", {"kind": kind.value, "instrument_id": str(target.instrument_id), "action": target.action.value})

            if emitted_targets:
                combined: dict[UUID, Decimal] = {}
                for spec in definition.strategies:
                    for instrument_id, raw_weight in sleeve_targets[spec.kind].items():
                        final_weight = raw_weight * spec.sleeve_budget
                        combined[instrument_id] = combined.get(instrument_id, Decimal()) + final_weight
                        contributions.append(SleeveContribution(run.run_id, strategy_run_ids[spec.kind], spec.kind, instrument_id, raw_weight, final_weight))
                emit(market_time, EventPriority.PORTFOLIO_NETTING, "SleevesNetted", {"targets": str(len(combined))})
                nav = account.cash + sum(Decimal(quantity) * latest_prices.get(instrument_id, Decimal()) for instrument_id, quantity in account.quantities.items())
                for instrument_id, target_weight in sorted(combined.items(), key=lambda item: str(item[0])):
                    bar = next((item for item in current_bars if item.instrument_id == instrument_id), None)
                    price = latest_prices.get(instrument_id)
                    if price is None or bar is None:
                        continue
                    market_rule = self.broker.market_rule(market_rules, bar.market, bar)
                    target_quantity = int(nav * target_weight / price) // market_rule.lot_size * market_rule.lot_size
                    open_signed = sum((item.remaining if item.side is Side.BUY else -item.remaining) for item in orders if item.instrument_id == instrument_id and item.status in (SimOrderStatus.OPEN, SimOrderStatus.PARTIALLY_FILLED))
                    delta = target_quantity - account.quantities.get(instrument_id, 0) - open_signed
                    delta = int(delta / market_rule.lot_size) * market_rule.lot_size
                    if delta == 0:
                        continue
                    side = Side.BUY if delta > 0 else Side.SELL
                    quantity = abs(delta)
                    if side is Side.SELL:
                        quantity = min(quantity, account.sellable.get(instrument_id, 0))
                        quantity = quantity // market_rule.lot_size * market_rule.lot_size
                    if quantity == 0:
                        continue
                    order = SimOrder(run.run_id, instrument_id, bar.market, side, SimOrderType.MARKET, quantity, market_time, bar_sequence + definition.execution_delay_bars)
                    orders.append(order)
                    emit(market_time, EventPriority.ORDER, "SimOrderSubmitted", {"order_id": str(order.order_id), "side": side.value, "quantity": str(quantity)})

            for index, order in enumerate(tuple(orders)):
                if order.status not in (SimOrderStatus.OPEN, SimOrderStatus.PARTIALLY_FILLED):
                    continue
                bar = next((item for item in current_bars if item.instrument_id == order.instrument_id), None)
                if bar is None:
                    continue
                rule = self.broker.market_rule(market_rules, bar.market, bar)
                cost = self.broker.cost_rule(cost_rules, bar.market, bar)
                updated, fill, reason = self.broker.match(order, bar, bar_sequence, rule, cost, definition.max_participation, account.sellable.get(order.instrument_id, 0), account.cash)
                order_index = next(i for i, item in enumerate(orders) if item.order_id == order.order_id)
                orders[order_index] = updated
                if fill is None:
                    emit(market_time, EventPriority.FILL, "SimOrderUnfilled", {"order_id": str(order.order_id), "reason": reason or "UNKNOWN"})
                    continue
                fills.append(fill)
                emit(market_time, EventPriority.FILL, "SimFillRecorded", {"fill_id": str(fill.fill_id), "order_id": str(order.order_id), "quantity": str(fill.quantity)})
                entries = account.apply_fill(fill, rule)
                emit(market_time, EventPriority.ACCOUNT, "SimAccountUpdated", {"entries": str(len(entries))}, fill.fill_id)

            if latest_prices:
                exposure = self._sleeve_exposure(definition, sleeve_targets)
                snapshot = account.snapshot(market_time, latest_prices, exposure)
                snapshots.append(snapshot)
                emit(market_time, EventPriority.VALUATION, "BacktestValued", {"snapshot_id": str(snapshot.snapshot_id), "nav": str(snapshot.nav)})

        metrics = calculate_metrics(run.run_id, tuple(snapshots), tuple(fills), definition.initial_cash)
        result_hash = self._hash({"input": run.input_hash, "orders": [self._stable_order(item) for item in orders], "fills": [self._stable_fill(item) for item in fills], "snapshots": [(item.as_of.isoformat(), str(item.cash), str(item.nav), item.content_hash) for item in snapshots], "metrics": [(item.name, str(item.value)) for item in metrics], "events": [(item.sequence, item.market_time.isoformat(), item.priority, item.event_type) for item in events]})
        completed = replace(run.transition(BacktestRunStatus.COMPLETED, datetime.now(timezone.utc)), result_hash=result_hash, last_sequence=sequence)
        return BacktestResult(definition, completed, tuple(events), tuple(orders), tuple(fills), tuple(account.ledger), tuple(snapshots), metrics, tuple(contributions))

    @staticmethod
    def _validate_inputs(definition, bars, market_rules, cost_rules, corporate_actions):
        if not bars:
            raise InvalidBacktest("bars are required")
        if any(bar.market_time < definition.start_at or bar.market_time > definition.end_at for bar in bars):
            raise InvalidBacktest("bar outside frozen window")
        if len({bar.bar_id for bar in bars}) != len(bars):
            raise InvalidBacktest("duplicate bar id")
        if any(action.available_at > definition.start_at and action.available_at > action.effective_at for action in corporate_actions):
            raise InvalidBacktest("future corporate action")
        broker = BrokerSimulator()
        for bar in bars:
            broker.market_rule(market_rules, bar.market, bar)
            broker.cost_rule(cost_rules, bar.market, bar)
            if bar.state is MarketState.DELISTED and definition.delisting_policy == "FAIL":
                raise InvalidBacktest("delisted instrument requires an explicit non-FAIL disposal policy")

    @staticmethod
    def _sleeve_exposure(definition, sleeve_targets):
        return {spec.kind.value: sum(sleeve_targets[spec.kind].values(), Decimal()) * spec.sleeve_budget for spec in definition.strategies}

    @staticmethod
    def _stable_order(item):
        return (str(item.instrument_id), item.market, item.side.value, item.order_type.value, item.quantity, item.submitted_at.isoformat(), item.eligible_after_bar_sequence, str(item.limit_price), item.filled_quantity, item.status.value)

    @staticmethod
    def _stable_fill(item):
        return (str(item.instrument_id), item.side.value, item.quantity, str(item.price), str(item.gross), str(item.commission), str(item.tax), str(item.platform_fee), str(item.slippage_cost), item.filled_at.isoformat(), str(item.bar_id))

    @staticmethod
    def _input_payload(definition, bars, market_rules, cost_rules, values, corporate_actions):
        return {"definition": definition, "bars": bars, "market_rules": market_rules, "cost_rules": cost_rules, "values": values, "corporate_actions": corporate_actions}

    @staticmethod
    def _hash(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()
