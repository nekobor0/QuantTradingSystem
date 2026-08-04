"""Pure strategy-level trade netting for V6 portfolio assembly."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _validate_sleeves(sleeves: dict[str, pd.Series], label: str) -> None:
    if not sleeves:
        raise ValueError(f"{label} sleeves are empty")
    for strategy, weights in sleeves.items():
        values = weights.astype(float)
        if values.index.has_duplicates:
            raise ValueError(f"{label}/{strategy} contains duplicate securities")
        if not np.isfinite(values.to_numpy()).all():
            raise ValueError(f"{label}/{strategy} contains non-finite weight")
        if (values < -1e-12).any():
            raise ValueError(f"{label}/{strategy} contains negative long-only weight")
    total = sum(float(weights.sum()) for weights in sleeves.values())
    if total > 1.0 + 1e-10:
        raise ValueError(f"{label} sleeve weights exceed total portfolio")


def net_strategy_trades(
    current_sleeves: dict[str, pd.Series],
    target_sleeves: dict[str, pd.Series],
    tradable: pd.Series | None = None,
) -> dict[str, Any]:
    """Net opposing strategy orders before applying a shared tradability gate."""
    if set(current_sleeves) != set(target_sleeves):
        raise ValueError("current and target strategy sets differ")
    _validate_sleeves(current_sleeves, "current")
    _validate_sleeves(target_sleeves, "target")
    names = pd.Index([])
    for sleeve in (*current_sleeves.values(), *target_sleeves.values()):
        names = names.union(sleeve.index)

    strategy_trades = pd.DataFrame(index=names)
    current_total = pd.Series(0.0, index=names)
    target_total = pd.Series(0.0, index=names)
    for strategy in sorted(current_sleeves):
        current = current_sleeves[strategy].reindex(names).fillna(0.0).astype(float)
        target = target_sleeves[strategy].reindex(names).fillna(0.0).astype(float)
        strategy_trades[strategy] = target - current
        current_total += current
        target_total += target

    intended = strategy_trades.sum(axis=1)
    can_trade = (
        pd.Series(True, index=names)
        if tradable is None
        else tradable.reindex(names).fillna(False).astype(bool)
    )
    executed = intended.where(can_trade, 0.0)
    unfilled = intended - executed
    detail = pd.DataFrame(
        {
            "current_weight": current_total,
            "target_weight": target_total,
            "intended_trade_weight": intended,
            "executed_trade_weight": executed,
            "unfilled_trade_weight": unfilled,
            "tradable": can_trade,
        }
    )
    gross_strategy_trade = float(strategy_trades.abs().sum().sum())
    gross_netted_trade = float(intended.abs().sum())
    return {
        "detail": detail,
        "strategy_trades": strategy_trades,
        "summary": {
            "strategies": len(strategy_trades.columns),
            "gross_strategy_trade_weight": gross_strategy_trade,
            "gross_netted_trade_weight": gross_netted_trade,
            "netting_saved_weight": gross_strategy_trade - gross_netted_trade,
            "executed_gross_trade_weight": float(executed.abs().sum()),
            "unfilled_gross_trade_weight": float(unfilled.abs().sum()),
            "cash_before": float(1.0 - current_total.sum()),
            "cash_target": float(1.0 - target_total.sum()),
        },
    }
