# Phase 1 checkpoint: supplemental-data rounds

## Scope and restart point

Phase 1 remains active. Research artifacts stay under `artifacts/alpha_phase1`; no supplemental data was written into Docker or the production schema. Resume from the frozen evaluation outputs listed below. Do not refetch existing non-empty shards.

## Tushare account verification

- Narrow live probes succeeded for `moneyflow`, `stk_holdernumber`, and `fina_indicator` with the existing local token.
- The smoke output is `artifacts/alpha_phase1/tushare/permission_smoke_round2.json`; it contains no token.
- `moneyflow` returned 5,142 rows for one known trading day, holder count returned 29 rows for one stock over two years, and `fina_indicator` returned 10 rows for one stock over two years.

## Supplemental datasets

- Money flow: 1,981 open-day shards from 2018-05-01 through 2026-06-30, 8,894,335 unique rows, 5,637 symbols.
- Holder count: 242,719 unique PIT rows, 5,576 symbols. Keys are `(ts_code, ann_date, end_date)`.
- Month-end valuation: 120 month snapshots from 2016-07 through 2026-06, 519,383 rows, 5,769 symbols.
- Leader-style acceptance audit: money-flow zero-row shards = 0; per-day rows range 3,264–5,198; duplicate money-flow keys = 0; duplicate holder keys = 0; missing holder announcement dates = 0.

## Pitfalls and handling

1. At 180 calls/minute with 16 workers, Tushare occasionally returned an empty DataFrame for a known open day instead of an explicit error. There were 294 such shards, clustered in time.
2. The 294 zero-row Parquet files were moved to recoverable `.unexpected_empty_*` quarantine files, not deleted. Re-fetching at 120 calls/minute returned normal market-sized frames, proving these were transient false empties.
3. Monthly recursive holder-count fetching was too slow when announcement-heavy months reached the 3,000-row response cap. Monthly ranges are now submitted concurrently while retaining one global rate limiter; capped ranges split recursively.
4. MvpSelect cash-flow files contain 58,607 rows with raw cash-flow values but missing both report and announcement dates. Those rows are unusable for PIT research and were not silently joined by report date.
5. Running the evaluator with global Python initially failed because `src` was not importable; the evaluator now lazily imports the original factor catalog only when no metadata file is supplied. This allows standalone frozen catalogs without changing factor calculations.

## Frozen factor rounds and outcomes

- Original price/volume round: 12 candidates, 0 pass. Output: `artifacts/alpha_phase1/factor_evaluation.json`.
- Share-supply and PIT annual-financial round: 10 candidates, 0 pass. Output: `artifacts/alpha_phase1/factor_evaluation_supplemental.json`.
- Money-flow and holder-count round: 7 candidates, 0 pass. Output: `artifacts/alpha_phase1/factor_evaluation_flow_holder.json`.
- Valuation and fundamental-change round: 7 candidates, 0 pass. Output: `artifacts/alpha_phase1/factor_evaluation_valuation.json`.

No sign was flipped and no threshold/window was relaxed after seeing results. At this checkpoint 36 theory-defined candidates have completed the same strict evaluation, with no eligible factor. Strongest observed pure IC values remain intraday reversal (0.0486, but fails domain/monotonicity/retention gates), one-month reversal (0.0407, but fails IR/domain/monotonicity), low maximum return (0.0365), turnover attention reversal (0.0295), and book-to-price (0.0247).

## Next action

Continue with a separately frozen, literature-defined market-microstructure batch or stop Phase 1 with an honest failure report if further independent hypotheses are exhausted. Do not manufacture five factors by sign flipping, parameter search, or weakening the gates. Before closing the next subtask, run the leader checklist and append a new checkpoint.
