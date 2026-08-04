from __future__ import annotations

from decimal import Decimal
from math import sqrt
from uuid import UUID

from .domain import BacktestMetric, BacktestSnapshot, SimFill


def calculate_metrics(run_id: UUID, snapshots: tuple[BacktestSnapshot, ...], fills: tuple[SimFill, ...], initial_cash: Decimal) -> tuple[BacktestMetric, ...]:
    navs = [float(item.nav) for item in snapshots]
    returns = [navs[index] / navs[index - 1] - 1 for index in range(1, len(navs)) if navs[index - 1] != 0]
    total_return = (Decimal(str(navs[-1])) / initial_cash - 1) if navs else Decimal()
    annual_return = Decimal(str((1 + float(total_return)) ** (252 / max(1, len(returns))) - 1)) if returns and total_return > -1 else Decimal()
    mean = sum(returns) / len(returns) if returns else 0.0
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1) if len(returns) > 1 else 0.0
    volatility = sqrt(variance) * sqrt(252)
    downside = [min(0.0, value) for value in returns]
    downside_deviation = sqrt(sum(value * value for value in downside) / len(downside)) * sqrt(252) if downside else 0.0
    sharpe = mean * 252 / volatility if volatility else 0.0
    sortino = mean * 252 / downside_deviation if downside_deviation else 0.0
    peak = navs[0] if navs else float(initial_cash)
    max_drawdown = 0.0
    for nav in navs:
        peak = max(peak, nav)
        max_drawdown = min(max_drawdown, nav / peak - 1)
    calmar = float(annual_return) / abs(max_drawdown) if max_drawdown else 0.0
    turnover = sum(float(fill.gross) for fill in fills) / (sum(navs) / len(navs)) if navs and sum(navs) else 0.0
    costs = sum((fill.commission + fill.tax + fill.platform_fee + fill.slippage_cost for fill in fills), Decimal())
    quantities: dict[UUID, int] = {}
    inventory_cost: dict[UUID, Decimal] = {}
    realized: list[Decimal] = []
    for fill in sorted(fills, key=lambda item: (item.filled_at, str(item.fill_id))):
        fees = fill.commission + fill.tax + fill.platform_fee
        if fill.side.value == "BUY":
            quantities[fill.instrument_id] = quantities.get(fill.instrument_id, 0) + fill.quantity
            inventory_cost[fill.instrument_id] = inventory_cost.get(fill.instrument_id, Decimal()) + fill.gross + fees
        else:
            quantity = quantities.get(fill.instrument_id, 0)
            average_cost = inventory_cost.get(fill.instrument_id, Decimal()) / quantity if quantity else Decimal()
            released = average_cost * fill.quantity
            realized.append(fill.gross - fees - released)
            quantities[fill.instrument_id] = quantity - fill.quantity
            inventory_cost[fill.instrument_id] = inventory_cost.get(fill.instrument_id, Decimal()) - released
    win_rate = sum(value > 0 for value in realized) / len(realized) if realized else 0.0
    gains = sum((value for value in realized if value > 0), Decimal())
    losses = abs(sum((value for value in realized if value < 0), Decimal()))
    profit_loss_ratio = float(gains / losses) if losses else 0.0
    values = {
        "total_return": total_return, "annual_return": annual_return, "volatility": Decimal(str(volatility)),
        "sharpe": Decimal(str(sharpe)), "sortino": Decimal(str(sortino)), "max_drawdown": Decimal(str(max_drawdown)),
        "calmar": Decimal(str(calmar)), "turnover": Decimal(str(turnover)), "win_rate": Decimal(str(win_rate)),
        "profit_loss_ratio": Decimal(str(profit_loss_ratio)), "cost": costs,
    }
    values = {name: value if name == "cost" else value.quantize(Decimal("0.0000000001")) for name, value in values.items()}
    return tuple(BacktestMetric(run_id, name, value, "ratio" if name != "cost" else "currency") for name, value in values.items())
