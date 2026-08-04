from datetime import timezone
from decimal import Decimal

from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from quant_trading_system.strategies import StrategyKind

from .domain import *
from .errors import RunConflict
from .tables import artifacts, contributions, definitions, events, fills, ledger, metrics, orders, runs, snapshots


class SqlAlchemyBacktestRepository:
    def __init__(self, engine): self.engine = engine
    @staticmethod
    def _a(value): return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value

    def find_run(self, input_hash):
        with self.engine.connect() as connection: row = connection.execute(select(runs).where(runs.c.input_hash == input_hash)).mappings().one_or_none()
        return None if row is None else self._run(row)

    def save_started(self, definition, run):
        try:
            with self.engine.begin() as connection:
                if connection.execute(select(definitions.c.definition_id).where(definitions.c.definition_id == definition.definition_id)).scalar_one_or_none() is None:
                    connection.execute(insert(definitions).values(**self._definition_values(definition)))
                if connection.execute(select(runs.c.run_id).where(runs.c.run_id == run.run_id)).scalar_one_or_none() is None:
                    connection.execute(insert(runs).values(**self._run_values(run)))
                else:
                    connection.execute(update(runs).where(runs.c.run_id == run.run_id).values(**self._run_values(run)))
        except IntegrityError as error: raise RunConflict(str(error.orig)) from error

    def save_result(self, result):
        with self.engine.begin() as connection:
            connection.execute(update(runs).where(runs.c.run_id == result.run.run_id).values(**self._run_values(result.run)))
            mappings = ((events, result.events, self._event_values), (orders, result.orders, self._order_values), (fills, result.fills, self._fill_values), (ledger, result.ledger, self._ledger_values), (snapshots, result.snapshots, self._snapshot_values), (metrics, result.metrics, self._metric_values), (contributions, result.contributions, self._contribution_values), (artifacts, result.artifacts, self._artifact_values))
            for table, values, mapper in mappings:
                if values: connection.execute(insert(table), [mapper(value) for value in values])

    def save_failed(self, run):
        with self.engine.begin() as connection: connection.execute(update(runs).where(runs.c.run_id == run.run_id).values(**self._run_values(run)))

    def get_result(self, run_id):
        with self.engine.connect() as connection:
            run_row = connection.execute(select(runs).where(runs.c.run_id == run_id)).mappings().one_or_none()
            if run_row is None or run_row.status != BacktestRunStatus.COMPLETED.value: return None
            definition_row = connection.execute(select(definitions).where(definitions.c.definition_id == run_row.definition_id)).mappings().one()
            event_rows = connection.execute(select(events).where(events.c.run_id == run_id).order_by(events.c.sequence)).mappings().all()
            order_rows = connection.execute(select(orders).where(orders.c.run_id == run_id)).mappings().all()
            fill_rows = connection.execute(select(fills).where(fills.c.run_id == run_id)).mappings().all()
            ledger_rows = connection.execute(select(ledger).where(ledger.c.run_id == run_id)).mappings().all()
            snapshot_rows = connection.execute(select(snapshots).where(snapshots.c.run_id == run_id).order_by(snapshots.c.as_of)).mappings().all()
            metric_rows = connection.execute(select(metrics).where(metrics.c.run_id == run_id)).mappings().all()
            contribution_rows = connection.execute(select(contributions).where(contributions.c.run_id == run_id)).mappings().all()
            artifact_rows = connection.execute(select(artifacts).where(artifacts.c.run_id == run_id)).mappings().all()
        return BacktestResult(self._definition(definition_row), self._run(run_row), tuple(self._event(row) for row in event_rows), tuple(self._order(row) for row in order_rows), tuple(self._fill(row) for row in fill_rows), tuple(self._ledger(row) for row in ledger_rows), tuple(self._snapshot(row) for row in snapshot_rows), tuple(self._metric(row) for row in metric_rows), tuple(self._contribution(row) for row in contribution_rows), tuple(self._artifact(row) for row in artifact_rows))

    @staticmethod
    def _definition_values(x): return {"definition_id": x.definition_id, "name": x.name, "strategies": [{"kind": s.kind.value, "version_id": str(s.version_id), "parameters_hash": s.parameters_hash, "sleeve_budget": str(s.sleeve_budget), "decision_frequency": s.decision_frequency} for s in x.strategies], "start_at": x.start_at, "end_at": x.end_at, "initial_cash": x.initial_cash, "base_currency": x.base_currency, "data_snapshot_id": x.data_snapshot_id, "universe_snapshot_id": x.universe_snapshot_id, "code_version": x.code_version, "random_seed": x.random_seed, "max_participation": x.max_participation, "execution_delay_bars": x.execution_delay_bars, "benchmark_id": x.benchmark_id, "delisting_policy": x.delisting_policy}
    @classmethod
    def _definition(cls, r): return BacktestDefinition(r.name, tuple(StrategySpec(StrategyKind(s["kind"]), __import__("uuid").UUID(s["version_id"]), s["parameters_hash"], Decimal(s["sleeve_budget"]), s["decision_frequency"]) for s in r.strategies), cls._a(r.start_at), cls._a(r.end_at), Decimal(r.initial_cash), r.base_currency, r.data_snapshot_id, r.universe_snapshot_id, r.code_version, r.random_seed, Decimal(r.max_participation), r.execution_delay_bars, r.benchmark_id, r.delisting_policy, r.definition_id)
    @staticmethod
    def _run_values(x): return {name: (getattr(x, name).value if name == "status" else getattr(x, name)) for name in ("run_id", "definition_id", "input_hash", "result_hash", "status", "started_at", "completed_at", "last_sequence", "error")}
    @classmethod
    def _run(cls, r): return BacktestRun(r.definition_id, r.input_hash, r.result_hash, BacktestRunStatus(r.status), cls._a(r.started_at), cls._a(r.completed_at), r.last_sequence, r.error, r.run_id)
    @staticmethod
    def _event_values(x): return {name: (int(getattr(x, name)) if name == "priority" else dict(getattr(x, name)) if name == "payload" else getattr(x, name)) for name in ("event_id", "run_id", "sequence", "market_time", "received_at", "priority", "event_type", "payload_version", "payload", "causation_id", "correlation_id")}
    @classmethod
    def _event(cls, r): return SimulationEvent(r.run_id, r.sequence, cls._a(r.market_time), cls._a(r.received_at), EventPriority(r.priority), r.event_type, r.payload_version, r.payload, r.causation_id, r.correlation_id, r.event_id)
    @staticmethod
    def _order_values(x): return {name: (getattr(x, name).value if name in ("side", "order_type", "status") else getattr(x, name)) for name in ("order_id", "run_id", "instrument_id", "market", "side", "order_type", "quantity", "submitted_at", "eligible_after_bar_sequence", "limit_price", "filled_quantity", "status", "reason")}
    @classmethod
    def _order(cls, r): return SimOrder(r.run_id, r.instrument_id, r.market, Side(r.side), SimOrderType(r.order_type), r.quantity, cls._a(r.submitted_at), r.eligible_after_bar_sequence, None if r.limit_price is None else Decimal(r.limit_price), r.filled_quantity, SimOrderStatus(r.status), r.reason, r.order_id)
    @staticmethod
    def _fill_values(x): return {name: (getattr(x, name).value if name == "side" else getattr(x, name)) for name in ("fill_id", "run_id", "order_id", "instrument_id", "side", "quantity", "price", "gross", "commission", "tax", "platform_fee", "slippage_cost", "filled_at", "bar_id")}
    @classmethod
    def _fill(cls, r): return SimFill(r.run_id, r.order_id, r.instrument_id, Side(r.side), r.quantity, Decimal(r.price), Decimal(r.gross), Decimal(r.commission), Decimal(r.tax), Decimal(r.platform_fee), Decimal(r.slippage_cost), cls._a(r.filled_at), r.bar_id, r.fill_id)
    @staticmethod
    def _ledger_values(x): return {name: (getattr(x, name).value if name == "kind" else getattr(x, name)) for name in ("entry_id", "run_id", "kind", "effective_at", "source_id", "cash_delta", "instrument_id", "quantity_delta", "fee_delta")}
    @classmethod
    def _ledger(cls, r): return SimLedgerEntry(r.run_id, LedgerKind(r.kind), cls._a(r.effective_at), r.source_id, Decimal(r.cash_delta), r.instrument_id, r.quantity_delta, Decimal(r.fee_delta), r.entry_id)
    @staticmethod
    def _snapshot_values(x): return {"snapshot_id": x.snapshot_id, "run_id": x.run_id, "as_of": x.as_of, "cash": x.cash, "positions": [{"instrument_id": str(p.instrument_id), "quantity": p.quantity, "sellable_quantity": p.sellable_quantity, "market_price": str(p.market_price), "market_value": str(p.market_value)} for p in x.positions], "nav": x.nav, "sleeve_exposure": {k: str(v) for k, v in x.sleeve_exposure.items()}, "content_hash": x.content_hash}
    @classmethod
    def _snapshot(cls, r): return BacktestSnapshot(r.run_id, cls._a(r.as_of), Decimal(r.cash), tuple(BacktestPosition(__import__("uuid").UUID(p["instrument_id"]), p["quantity"], p["sellable_quantity"], Decimal(p["market_price"]), Decimal(p["market_value"])) for p in r.positions), Decimal(r.nav), {k: Decimal(v) for k, v in r.sleeve_exposure.items()}, r.content_hash, r.snapshot_id)
    @staticmethod
    def _metric_values(x): return {"metric_id": x.metric_id, "run_id": x.run_id, "name": x.name, "value": x.value, "unit": x.unit, "scope": x.scope}
    @staticmethod
    def _metric(r): return BacktestMetric(r.run_id, r.name, None if r.value is None else Decimal(r.value), r.unit, r.scope, r.metric_id)
    @staticmethod
    def _contribution_values(x): return {"contribution_id": x.contribution_id, "run_id": x.run_id, "strategy_run_id": x.strategy_run_id, "kind": x.kind.value, "instrument_id": x.instrument_id, "raw_weight": x.raw_weight, "final_weight": x.final_weight}
    @staticmethod
    def _contribution(r): return SleeveContribution(r.run_id, r.strategy_run_id, StrategyKind(r.kind), r.instrument_id, Decimal(r.raw_weight), Decimal(r.final_weight), r.contribution_id)
    @staticmethod
    def _artifact_values(x): return {"artifact_id": x.artifact_id, "run_id": x.run_id, "artifact_type": x.artifact_type, "content_hash": x.content_hash, "reference": x.reference}
    @staticmethod
    def _artifact(r): return BacktestArtifact(r.run_id, r.artifact_type, r.content_hash, r.reference, r.artifact_id)
