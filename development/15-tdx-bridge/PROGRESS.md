# TDX bridge progress

- Goal: ingest TdxQuant historical backfills and explicit-date daily increments through the existing market-data quality gate and SQLAlchemy repository.
- Order: freeze evidence; implement HTTP adapter and normalization; wire CLI to existing data layer; test; attempt the live January 2024 acceptance.
- Largest risk: the running terminal has no TQ component/HTTP listener, while PostgreSQL and its Python driver are also unavailable.
- Baseline: `1486 passed in 9.21s`, 0 skipped on 2026-07-28.
- Scope: historical `1d` only; no real-time subscription and no trading API.
- TQ prerequisite recheck: quantitative terminal is running from `D:\TDX`; `tqcenter.py`, both communication DLLs, and port 17709 are available.
- Live source evidence: `600000.SH` returned 22 daily bars for 2024-01-02 through 2024-01-31 after the user downloaded post-market history.
- Implementation: loopback HTTP client, raw-first normalization bridge, existing SQLAlchemy data-layer wiring, backfill/incremental/verify CLI, tests, and integration documentation are complete.
- Live isolated acceptance: batch `e6a63eb5-4e26-4b66-b3ee-4a468352030b`, checksum `33423a66...678e`, status `PUBLISHED`, 22 rows; identical rerun reused the batch and stayed at 22 rows.
- Reverse evidence: changing `fill_data` to true failed the frozen request test; restoring false passed.
- Final local evidence: `1497 passed in 14.47s`, 0 skipped; focused mypy/compileall and documentation validation passed.
- Status: feature and production PostgreSQL integration complete; full-universe historical import is running with resumable checkpoints.
- Production update: PostgreSQL/TimescaleDB is live on a loopback-only override, all 14 migrations applied, and `.venv` includes `psycopg 3.3.4`.
- Bulk update: manifest export/import, batches, atomic resume checkpoints, retries, per-symbol fallback, coverage reporting, master-data bootstrap, and cached PIT resolution implemented; full suite `1503 passed`, focused mypy clean.
- Production smoke: four securities published 19,710 distinct daily bars from 2005-01-01 through 2026-07-28 with zero failures. Full 7,198-symbol A-share/ETF import is in progress.
