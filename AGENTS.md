# Project operating policy

## Scope and safety

This repository contains quantitative research, backtesting, risk-control, execution-ledger, and application code. Market data, credentials, account/order/fill/position exports, databases, logs, caches, models, and generated artifacts must never be committed.

- Never print or expose credentials.
- Never connect tests to live trading or submit, cancel, or modify live orders.
- Default to paper, mock, or offline behavior. Keep `TRADING_MODE=paper`, `ALLOW_LIVE_TRADING=false`, and `ENABLE_ORDER_SUBMISSION=false` in examples and tests.
- Never bypass risk controls or weaken a safety assertion merely to make a test pass.

## Branches and task start

- `main` is stable and protected. Daily work belongs on `codex/*` task branches created from `codex/develop`.
- Never force-push, rewrite shared history, automatically roll back `main`, or delete a user-created branch.
- At task start run `git status --short --branch`, `git fetch --prune origin`, and record `git rev-parse HEAD` as the baseline.
- Preserve unrelated user changes. If baseline checks already fail, report that fact and do not attribute it to new work.

## Required checks

Quick checks:

```powershell
python scripts/git_safety_check.py --worktree
python -m compileall -q src scripts
python -m mypy src/quant_trading_system --exclude 'src[\\/]quant_trading_system[\\/]research[\\/]'
python -m pytest -q tests/risk tests/execution_ledger tests/api_ui
```

Before push or merge:

```powershell
python scripts/git_safety_check.py --tracked
python -m compileall -q src scripts
python -m mypy src/quant_trading_system --exclude 'src[\\/]quant_trading_system[\\/]research[\\/]'
python -m pytest -q
python -m pytest -q tests/risk tests/execution_ledger tests/api_ui
```

The focused risk/execution/API suite is the trading-safety check. The in-memory backtest tests under `tests/backtest` are the deterministic offline backtest smoke coverage. The typed application packages are checked by mypy; `research/` is excluded because its pandas/scipy modules do not yet have a clean typing baseline and remain covered by pytest. No separate lint tool is configured; `compileall` is the current syntax check.

## Checkpoints and risky changes

Order routing, authentication, sizing, leverage, liquidation, stop-loss, risk limits, accounting, PnL, time zones, calendars, migrations, dependencies, and changes over five files or about 200 lines are high risk. Before them, require a clean worktree, passing quick checks, and a pushed checkpoint on a Codex branch.

Create checkpoints after coherent passing units, before high-risk work, and at task completion:

```powershell
.\scripts\git_checkpoint.ps1 "chore: describe the stable checkpoint"
```

Run `.\scripts\git_sync_status.ps1` at task start and end once `origin` exists.

## Autonomous rollback

Autonomous rollback is allowed only on a Codex-created branch or isolated worktree with a recorded, passing baseline, a deterministic regression caused by the current change, and no user/external/live/database state involved. Save a recovery patch under ignored `recovery/` first. Preview untracked cleanup and remove only files created by the current task.

- Make at most two focused repair attempts.
- For an uncommitted current-task regression, restore only current-task files to the baseline; never discard unrelated work.
- For a pushed bad commit, use `git revert` and push the revert. Never force-push.
- Do not roll back solely for changed Sharpe/return/drawdown, stochastic output, network/API failure, or a pre-existing failure unless the task froze a deterministic acceptance threshold.
- Stop for user approval on `main`, merge reverts, migrations, external state, possible live orders/account changes, already-pushed secrets, ambiguous user work, or any deletion/overwrite risk.

At task end report branch, baseline/final commits, remote push, checks, exclusions, rollback actions, and remaining risks.
