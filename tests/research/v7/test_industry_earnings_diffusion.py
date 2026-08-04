import json

import numpy as np
import pandas as pd
import pytest

from scripts.v7.backfill_f7_financials import (
    FINANCIAL_FIELDS,
    REPORT_FIELDS,
    _validate_financial,
    _validate_report,
    _load_verified_report_marker,
    _load_verified_shard,
    _write_shard,
    dataset_lock,
    month_ranges,
    rate_limit_delay,
    report_page_state,
)
from scripts.v7.run_industry_earnings_diffusion_v7 import (
    build_data_manifest,
    build_overlay_portfolio,
    coverage_audit,
    prepare_execution_labels,
    raw_data_quality,
    require_complete_backfill,
    stage_p,
    stage_s,
    write_report,
)
from quant_trading_system.research.v7.industry_earnings_diffusion import (
    aggregate_industry_diffusion,
    analyst_revision_pit,
    build_csi1000_member_panel,
    financial_acceleration_pit,
    industry_tilts,
    monthly_partial_rank_ic,
    stock_forward_return_3m,
)


def test_month_ranges_clip_boundaries():
    assert month_ranges("20250115", "20250302") == [
        ("202501", "20250115", "20250131"),
        ("202502", "20250201", "20250228"),
        ("202503", "20250301", "20250302"),
    ]


def test_month_ranges_reject_reverse_range():
    with pytest.raises(ValueError, match="must not exceed"):
        month_ranges("20250302", "20250115")


def test_financial_validator_rejects_symbol_filter_failure():
    frame = pd.DataFrame([{column: None for column in FINANCIAL_FIELDS.split(",")}])
    frame["ts_code"] = "000002.SZ"
    with pytest.raises(ValueError, match="symbol filter failed"):
        _validate_financial(frame, "000001.SZ")


def test_report_validator_rejects_future_page_leakage():
    frame = pd.DataFrame([{column: None for column in REPORT_FIELDS.split(",")}])
    frame["report_date"] = "20250201"
    with pytest.raises(ValueError, match="date filter failed"):
        _validate_report(frame, "20250101", "20250131")


def test_report_empty_first_page_is_not_silently_completed():
    with pytest.raises(ValueError, match="empty first page"):
        _validate_report(pd.DataFrame(), "20250101", "20250131")
    _validate_report(pd.DataFrame(), "20250101", "20250131", allow_empty=True)


def test_rate_limit_delay_distinguishes_minute_hour_and_day():
    assert rate_limit_delay("1次/分钟", 1) == 65
    assert rate_limit_delay("10次/小时", 1) == 3605
    assert rate_limit_delay("other", 3) == 4
    assert 60 < rate_limit_delay("10次/天", 1) <= 24 * 3600 + 65


def test_report_pagination_handles_documented_and_verified_page_caps():
    effective, done = report_page_state(5000, 5000, None)
    assert (effective, done) == (5000, False)
    assert report_page_state(4339, 5000, effective) == (5000, True)

    effective, done = report_page_state(3000, 5000, None)
    assert (effective, done) == (3000, False)
    assert report_page_state(3000, 5000, effective) == (3000, False)
    assert report_page_state(339, 5000, effective) == (3000, True)
    assert report_page_state(2500, 5000, None) == (None, True)


def test_shard_is_immutable_and_has_hash_sidecar(tmp_path):
    path = tmp_path / "one.parquet"
    frame = pd.DataFrame({"value": [1]})
    metadata = _write_shard(frame, path, {"api_name": "test"})
    assert len(metadata["sha256"]) == 64
    assert path.with_suffix(".json").exists()
    with pytest.raises(FileExistsError, match="immutable shard"):
        _write_shard(frame, path, {"api_name": "test"})


def test_cached_shard_hash_drift_is_rejected(tmp_path):
    path = tmp_path / "one.parquet"
    _write_shard(pd.DataFrame({"value": [1]}), path, {"api_name": "test"})
    loaded, _ = _load_verified_shard(path)
    assert loaded["value"].tolist() == [1]
    pd.DataFrame({"value": [2]}).to_parquet(path, index=False)
    with pytest.raises(ValueError, match="hash drift"):
        _load_verified_shard(path)


def test_report_marker_is_verified_against_immutable_pages(tmp_path):
    path = tmp_path / "202501_000000.parquet"
    frame = pd.DataFrame([{column: None for column in REPORT_FIELDS.split(",")}])
    frame["report_date"] = "20250115"
    metadata = _write_shard(
        frame,
        path,
        {"api_name": "report_rc", "limit": 5000, "offset": 0},
    )
    marker = tmp_path / "202501.complete.json"
    marker.write_text(
        json.dumps(
            {
                "month": "202501",
                "rows": 1,
                "pages": [{"path": str(path), "rows": 1, "sha256": metadata["sha256"]}],
            }
        ),
        encoding="utf-8",
    )
    assert _load_verified_report_marker(marker, "20250101", "20250131")["rows"] == 1
    payload = json.loads(marker.read_text(encoding="utf-8"))
    payload["rows"] = 2
    marker.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="marker row drift"):
        _load_verified_report_marker(marker, "20250101", "20250131")


def test_report_marker_rejects_ambiguous_documented_cap(tmp_path):
    path = tmp_path / "202501_000000.parquet"
    frame = pd.DataFrame([{column: None for column in REPORT_FIELDS.split(",")} for _ in range(3000)])
    frame["report_date"] = "20250115"
    metadata = _write_shard(
        frame,
        path,
        {"api_name": "report_rc", "limit": 5000, "offset": 0},
    )
    marker = tmp_path / "202501.complete.json"
    marker.write_text(
        json.dumps(
            {
                "month": "202501",
                "rows": 3000,
                "pages": [{"path": str(path), "rows": 3000, "sha256": metadata["sha256"]}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="incomplete pagination"):
        _load_verified_report_marker(marker, "20250101", "20250131")

    report_root = tmp_path / "backfill" / "shards" / "report_rc"
    report_root.mkdir(parents=True)
    nested_path = report_root / path.name
    nested_metadata = _write_shard(
        frame,
        nested_path,
        {"api_name": "report_rc", "limit": 5000, "offset": 0},
    )
    nested_marker = report_root / marker.name
    nested_marker.write_text(
        json.dumps(
            {
                "month": "202501",
                "rows": 3000,
                "pages": [
                    {"path": str(nested_path), "rows": 3000, "sha256": nested_metadata["sha256"]}
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="incomplete pagination"):
        require_complete_backfill(tmp_path / "backfill", 0, {"202501"})


def test_dataset_lock_rejects_a_second_live_worker(tmp_path):
    with dataset_lock(tmp_path, "report_rc", "first"):
        with pytest.raises(RuntimeError, match="active dataset lock"):
            with dataset_lock(tmp_path, "report_rc", "second"):
                pass
    assert not (tmp_path / "locks" / "report_rc.lock").exists()


def test_dataset_lock_recovers_a_dead_owner(tmp_path):
    path = tmp_path / "locks" / "report_rc.lock"
    path.parent.mkdir(parents=True)
    path.write_text('{"pid": 2147483647, "nonce": "dead"}', encoding="utf-8")
    with dataset_lock(tmp_path, "report_rc", "replacement"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["nonce"] == "replacement"
    assert not path.exists()


def test_future_financial_announcement_does_not_change_old_signal():
    base = pd.DataFrame(
        {
            "ts_code": ["A", "A"],
            "ann_date": ["20240420", "20240820"],
            "end_date": ["20240331", "20240630"],
            "update_flag": [1, 1],
            "q_sales_yoy": [10.0, 30.0],
            "dt_netprofit_yoy": [5.0, 20.0],
            "q_roe": [2.0, 3.0],
        }
    )
    date = [pd.Timestamp("2024-08-31")]
    old = financial_acceleration_pit(base, date)
    future = base.iloc[[-1]].assign(ann_date="20240915", q_sales_yoy=99.0)
    new = financial_acceleration_pit(pd.concat([base, future]), date)
    pd.testing.assert_frame_equal(old, new)
    assert old.iloc[0]["revenue_acceleration"] == 20.0


def test_missing_previous_quarter_is_not_treated_as_acceleration():
    frame = pd.DataFrame(
        {
            "ts_code": ["A", "A"],
            "ann_date": ["20240420", "20241020"],
            "end_date": ["20240331", "20240930"],
            "update_flag": [1, 1],
            "q_sales_yoy": [10.0, 30.0],
            "dt_netprofit_yoy": [5.0, 20.0],
            "q_roe": [2.0, 3.0],
        }
    )
    result = financial_acceleration_pit(frame, [pd.Timestamp("2024-10-31")])
    assert np.isnan(result.iloc[0]["revenue_acceleration"])


def test_analyst_revision_uses_same_target_and_excludes_future_report():
    reports = pd.DataFrame(
        {
            "ts_code": ["A", "A", "A"],
            "report_date": ["20240420", "20240520", "20240602"],
            "org_name": ["X", "X", "X"],
            "quarter": ["2025Q4", "2025Q4", "2025Q4"],
            "np": [100.0, 110.0, 999.0],
            "create_time": ["2024-04-20", "2024-05-20", "2024-06-02"],
        }
    )
    result = analyst_revision_pit(reports, [pd.Timestamp("2024-05-31")])
    assert result.iloc[0]["target_quarter"] == "2025Q4"
    assert np.isclose(result.iloc[0]["earnings_revision"], np.log(1.1))
    assert result.iloc[0]["latest_report_date"] == pd.Timestamp("2024-05-20")
    assert result.iloc[0]["previous_latest_report_date"] == pd.Timestamp("2024-04-20")


def test_january_target_roll_is_missing_not_spliced():
    reports = pd.DataFrame(columns=["ts_code", "report_date", "org_name", "quarter", "np", "create_time"])
    assert analyst_revision_pit(reports, [pd.Timestamp("2025-01-31")]).empty


def test_industry_aggregation_winsorizes_company_values_before_weighted_median():
    date = pd.Timestamp("2024-05-31")
    stocks = [f"S{i}" for i in range(5)]
    members = pd.DataFrame(
        {
            "signal_date": date,
            "ts_code": stocks,
            "l1_code": "I1",
            "total_mv": [1.0, 1.0, 1.0, 1.0, 100.0],
        }
    )
    financial = pd.DataFrame(
        {
            "signal_date": date,
            "ts_code": stocks,
            "revenue_acceleration": [-2.0, -1.0, 1.0, 2.0, 999.0],
            "deducted_profit_acceleration": [-2.0, -1.0, 1.0, 2.0, 999.0],
            "roe_improvement": [-2.0, -1.0, 1.0, 2.0, 999.0],
        }
    )
    analyst = pd.DataFrame(
        {
            "signal_date": date,
            "ts_code": stocks,
            "earnings_revision": [-0.2, -0.1, 0.1, 0.2, 1000.0],
        }
    )
    result = aggregate_industry_diffusion(members, financial, analyst).iloc[0]
    expected_upper = analyst["earnings_revision"].quantile(0.99)
    assert np.isclose(result["earnings_revision_weighted_median"], expected_upper)
    assert result["earnings_revision_weighted_median"] < 1000.0


def test_nonmember_and_future_industry_membership_are_excluded():
    weights = pd.DataFrame({"trade_date": ["20240131", "20240131"], "con_code": ["A", "B"], "weight": [0.1, 0.1]})
    industries = pd.DataFrame(
        {
            "ts_code": ["A", "A", "B"],
            "l1_code": ["OLD", "FUTURE", "ENDED"],
            "in_date": ["20200101", "20240201", "20200101"],
            "out_date": [None, None, "20230101"],
        }
    )
    caps = pd.DataFrame({"trade_date": ["20240131", "20240131"], "ts_code": ["A", "B"], "total_mv": [1.0, 2.0]})
    panel = build_csi1000_member_panel(weights, industries, caps)
    assert panel[["ts_code", "l1_code"]].values.tolist() == [["A", "OLD"]]


def test_same_industry_overlap_is_deduplicated_but_conflict_fails():
    weights = pd.DataFrame({"trade_date": ["20240131"], "con_code": ["A"], "weight": [0.1]})
    caps = pd.DataFrame({"trade_date": ["20240131"], "ts_code": ["A"], "total_mv": [1.0]})
    same = pd.DataFrame(
        {
            "ts_code": ["A", "A"],
            "l1_code": ["I1", "I1"],
            "in_date": ["20200101", "20200101"],
            "out_date": [None, "20260630"],
        }
    )
    assert len(build_csi1000_member_panel(weights, same, caps)) == 1
    conflict = same.assign(l1_code=["I1", "I2"])
    with pytest.raises(ValueError, match="conflicting overlapping"):
        build_csi1000_member_panel(weights, conflict, caps)


def test_three_month_return_uses_consecutive_signal_months():
    labels = pd.DataFrame(
        {
            "ts_code": ["A", "A", "A", "A"],
            "signal_date": pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31", "2024-04-30"]),
            "mark_return_1m": [0.1, 0.2, -0.1, 0.5],
        }
    )
    result = stock_forward_return_3m(labels).set_index("signal_date")
    assert np.isclose(result.loc[pd.Timestamp("2024-01-31"), "stock_return_3m"], 1.1 * 1.2 * 0.9 - 1)
    assert np.isnan(result.loc[pd.Timestamp("2024-03-31"), "stock_return_3m"])


def test_three_month_return_excludes_untradable_initial_entry():
    labels = pd.DataFrame(
        {
            "ts_code": "A",
            "signal_date": pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31"]),
            "mark_return_1m": [0.1, 0.2, 0.3],
            "entry_tradable": [False, True, True],
        }
    )
    result = stock_forward_return_3m(labels).set_index("signal_date")
    assert np.isnan(result.loc[pd.Timestamp("2024-01-31"), "stock_return_3m"])


def test_three_month_return_keeps_marks_for_untradable_existing_holding():
    labels = pd.DataFrame(
        {
            "ts_code": "A",
            "signal_date": pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31"]),
            "mark_return_1m": [0.1, 0.2, 0.3],
            "entry_tradable": [True, False, True],
        }
    )
    result = stock_forward_return_3m(labels).set_index("signal_date")
    assert np.isclose(
        result.loc[pd.Timestamp("2024-01-31"), "stock_return_3m"],
        1.1 * 1.2 * 1.3 - 1,
    )


def test_industry_tilts_are_zero_net_fixed_l1_and_capped():
    frame = pd.DataFrame(
        {
            "signal_date": pd.Timestamp("2024-01-31"),
            "l1_code": [f"I{i:02d}" for i in range(15)],
            "industry_earnings_diffusion": np.arange(15, dtype=float),
        }
    )
    result = industry_tilts(frame)
    assert abs(result["industry_tilt"].sum()) < 1e-12
    assert np.isclose(result["industry_tilt"].abs().sum(), 0.10)
    assert result["industry_tilt"].abs().max() <= 0.02


def test_missing_january_signal_carries_only_unexpired_cohorts():
    industries = [f"I{i:02d}" for i in range(15)]
    rows = []
    for date, offset in (("2023-11-30", 0.0), ("2023-12-31", 1.0), ("2024-01-31", np.nan), ("2024-02-29", 2.0)):
        rows.extend(
            {
                "signal_date": pd.Timestamp(date),
                "l1_code": industry,
                "industry_earnings_diffusion": value + offset if np.isfinite(offset) else np.nan,
            }
            for value, industry in enumerate(industries)
        )
    result = industry_tilts(pd.DataFrame(rows))
    assert pd.Timestamp("2024-01-31") in set(result["signal_date"])
    assert np.isclose(
        result.loc[result["signal_date"].eq(pd.Timestamp("2024-02-29")), "industry_tilt"].abs().sum(),
        0.10,
    )


def test_partial_ic_removes_price_momentum_copy():
    frame = pd.DataFrame(
        {
            "signal_date": pd.Timestamp("2024-01-31"),
            "signal": np.arange(10, dtype=float),
            "momentum": np.arange(10, dtype=float),
            "future": np.arange(10, dtype=float),
        }
    )
    result = monthly_partial_rank_ic(frame, "signal", "future", "momentum")
    assert result.empty or abs(result.iloc[0]) < 0.2


def test_overlay_mapping_is_long_only_full_invested_and_ten_percent_l1():
    date = pd.Timestamp("2024-01-31")
    industries = [f"I{i:02d}" for i in range(15)]
    stocks = [f"S{i:02d}" for i in range(15)]
    scores = pd.DataFrame(
        {"signal_date": date, "l1_code": industries, "industry_earnings_diffusion": np.arange(15, dtype=float)}
    )
    members = pd.DataFrame(
        {
            "signal_date": date,
            "ts_code": stocks,
            "l1_code": industries,
            "benchmark_weight": 1 / 15,
            "total_mv": 1e9,
        }
    )
    labels = pd.DataFrame({"signal_date": date, "ts_code": stocks, "mark_return_1m": 0.01})
    baseline_holdings = pd.DataFrame(
        {"signal_date": date, "ts_code": stocks, "weight": 1 / 15, "trade_weight": 1 / 15}
    )
    baseline_monthly = pd.DataFrame(
        {
            "signal_date": [date],
            "portfolio_gross_return": [0.01],
            "portfolio_net_return": [0.0095],
            "benchmark_return": [0.01],
            "turnover": [1.0],
            "cost": [0.0005],
        }
    )
    monthly, holdings, _ = build_overlay_portfolio(
        scores, members, labels, baseline_monthly, baseline_holdings
    )
    assert np.isclose(holdings["weight"].sum(), 1.0)
    assert holdings["weight"].min() >= 0
    assert np.isclose(monthly.iloc[0]["industry_tilt_l1"], 0.10)
    assert monthly.iloc[0]["maximum_industry_tilt"] <= 0.02


def test_overlay_additions_require_eligibility_and_missing_marks_are_conservative():
    date = pd.Timestamp("2024-01-31")
    industries = [f"I{i:02d}" for i in range(15)]
    stocks = [f"S{i:02d}" for i in range(15)] + ["S14B"]
    stock_industries = industries + ["I14"]
    scores = pd.DataFrame(
        {"signal_date": date, "l1_code": industries, "industry_earnings_diffusion": np.arange(15, dtype=float)}
    )
    members = pd.DataFrame(
        {
            "signal_date": date,
            "ts_code": stocks,
            "l1_code": stock_industries,
            "benchmark_weight": 1 / 16,
            "total_mv": 1e9,
        }
    )
    labels = pd.DataFrame(
        {
            "signal_date": date,
            "ts_code": stocks,
            "mark_return_1m": [np.nan, *([0.0] * 13), -0.5, 0.5],
            "entry_tradable": True,
            "eligible_entry": [*([True] * 14), False, True],
            "forced_exit": False,
        }
    )
    baseline_holdings = pd.DataFrame(
        {"signal_date": date, "ts_code": stocks, "weight": 1 / 16, "trade_weight": 1 / 16}
    )
    baseline_monthly = pd.DataFrame(
        {
            "signal_date": [date],
            "portfolio_gross_return": [0.0],
            "portfolio_net_return": [-0.0005],
            "benchmark_return": [0.0],
            "turnover": [1.0],
            "cost": [0.0005],
        }
    )
    monthly, holdings, contributions = build_overlay_portfolio(
        scores, members, labels, baseline_monthly, baseline_holdings
    )
    weights = holdings.set_index("ts_code")["weight"]
    assert np.isclose(weights["S14"], 1 / 16)
    assert weights["S14B"] > 1 / 16
    assert monthly.iloc[0]["missing_return_weight"] > 0
    assert monthly.iloc[0]["portfolio_gross_return"] < 0
    assert np.isclose(contributions["active_return_contribution"].sum(), monthly.iloc[0]["overlay_return"])


def test_execution_labels_separate_new_entry_eligibility_from_forced_exit():
    labels = pd.DataFrame(
        {
            "ts_code": ["ST", "DELIST", "GOOD"],
            "signal_date": pd.Timestamp("2024-01-31"),
            "entry_date": pd.Timestamp("2024-02-01"),
            "exit_date": pd.Timestamp("2024-03-01"),
            "entry_tradable": [True, False, True],
            "exit_tradable": True,
            "mark_return_1m": [0.0, np.nan, 0.0],
        }
    )
    basic = pd.DataFrame(
        {"ts_code": ["ST", "DELIST", "GOOD"], "delist_date": [None, "20240131", None]}
    )
    st = pd.DataFrame({"ts_code": ["ST"], "trade_date": ["20240131"]})
    adv = labels[["ts_code", "signal_date", "entry_date"]].assign(adv20_cny=1e8)
    result = prepare_execution_labels(labels, basic, st, adv).set_index("ts_code")
    assert not result.loc["ST", "eligible_entry"]
    assert result.loc["DELIST", "forced_exit"]
    assert not result.loc["DELIST", "eligible_entry"]
    assert result.loc["GOOD", "eligible_entry"]


def test_overlay_forced_exit_removes_delisted_pretrade_holding():
    dates = pd.to_datetime(["2024-01-31", "2024-02-29"])
    industries = [f"I{i:02d}" for i in range(15)]
    first_stocks = [f"A{i:02d}" for i in range(15)]
    second_stocks = ["B00", *first_stocks[1:]]
    scores = pd.concat(
        [
            pd.DataFrame(
                {"signal_date": date, "l1_code": industries, "industry_earnings_diffusion": np.arange(15)}
            )
            for date in dates
        ],
        ignore_index=True,
    )
    members = pd.concat(
        [
            pd.DataFrame(
                {
                    "signal_date": date,
                    "ts_code": stocks,
                    "l1_code": industries,
                    "benchmark_weight": 1 / 15,
                    "total_mv": 1e9,
                }
            )
            for date, stocks in zip(dates, [first_stocks, second_stocks], strict=True)
        ],
        ignore_index=True,
    )
    labels = []
    for date, stocks in zip(dates, [first_stocks, [*second_stocks, "A00"]], strict=True):
        for stock in stocks:
            labels.append(
                {
                    "signal_date": date,
                    "ts_code": stock,
                    "mark_return_1m": 0.0,
                    "entry_tradable": stock != "A00" or date == dates[0],
                    "eligible_entry": stock != "A00" or date == dates[0],
                    "forced_exit": stock == "A00" and date == dates[1],
                }
            )
    baseline_holdings = pd.concat(
        [
            pd.DataFrame(
                {"signal_date": date, "ts_code": stocks, "weight": 1 / 15, "trade_weight": 0.0}
            )
            for date, stocks in zip(dates, [first_stocks, second_stocks], strict=True)
        ],
        ignore_index=True,
    )
    baseline_monthly = pd.DataFrame(
        {
            "signal_date": dates,
            "portfolio_gross_return": 0.0,
            "portfolio_net_return": 0.0,
            "benchmark_return": 0.0,
            "turnover": 0.0,
            "cost": 0.0,
        }
    )
    _, holdings, _ = build_overlay_portfolio(scores, members, pd.DataFrame(labels), baseline_monthly, baseline_holdings)
    second = holdings[holdings["signal_date"].eq(dates[1])]
    assert "A00" not in set(second["ts_code"])
    assert "B00" in set(second["ts_code"])


def test_stage_s_and_coverage_run_on_preregistered_shape():
    dates = pd.date_range("2019-01-31", periods=60, freq="ME")
    industries = [f"I{i:02d}" for i in range(15)]
    rows = []
    for date in dates:
        for index, industry in enumerate(industries):
            rows.append(
                {
                    "signal_date": date,
                    "l1_code": industry,
                    "positive_revenue_acceleration_share": index / 15,
                    "positive_deducted_profit_acceleration_share": index / 15,
                    "positive_roe_improvement_share": index / 15,
                    "earnings_revision_weighted_median": index / 15,
                    "industry_earnings_diffusion": float(index),
                }
            )
    scores = pd.DataFrame(rows)
    coverage_monthly, audit = coverage_audit(scores)
    assert audit["passes"]
    future = scores[["signal_date", "l1_code"]].assign(
        industry_return_3m=scores["industry_earnings_diffusion"] * 0.01
    )
    momentum = scores[["signal_date", "l1_code"]].assign(
        relative_momentum=np.tile(np.sin(np.arange(15)), 60)
    )
    result = stage_s(scores, future, momentum, set(coverage_monthly["signal_date"]))
    assert result["months"] == 60
    assert result["mean_rank_ic_3m"] > 0.99
    assert set(result["component_rank_ic"]) == {
        "positive_revenue_acceleration_share",
        "positive_deducted_profit_acceleration_share",
        "positive_roe_improvement_share",
        "earnings_revision_weighted_median",
    }
    assert len(result["annual_rank_ic"]) >= 5
    assert len(result["industry_diagnostics"]) == 15


def test_data_manifest_and_raw_quality_are_machine_auditable(tmp_path):
    shard = tmp_path / "one.parquet"
    pd.DataFrame({"x": [1, 2]}).to_parquet(shard, index=False)
    manifest = build_data_manifest([shard], [], project_root=tmp_path)
    assert manifest["datasets"]["fina_indicator"]["files"] == 1
    assert manifest["datasets"]["fina_indicator"]["rows"] == 2
    assert len(manifest["datasets"]["fina_indicator"]["root_sha256"]) == 64

    financial = pd.DataFrame(
        {
            "ts_code": ["A", "A"],
            "ann_date": ["20240420", "20240420"],
            "end_date": ["20240331", "20240331"],
            "update_flag": [1, 1],
            "q_sales_yoy": [1.0, 1.0],
            "dt_netprofit_yoy": [2.0, 2.0],
            "q_roe": [3.0, 3.0],
        }
    )
    reports = pd.DataFrame(
        {
            "ts_code": ["A"],
            "report_date": ["20240520"],
            "org_name": ["O"],
            "quarter": ["2025Q4"],
            "np": [-1.0],
            "create_time": ["2024-05-20"],
        }
    )
    quality = raw_data_quality(financial, reports)
    assert quality["financial_exact_duplicate_rows"] == 1
    assert quality["report_nonpositive_np_rows"] == 1
    assert quality["report_target_quarters"] == 1


def test_f7_report_uses_all_v7_standard_sections(tmp_path):
    result = {
        "decision": "REJECTED",
        "registration_sha256": "r" * 64,
        "config_sha256": "c" * 64,
        "workspace_commit": "UNAVAILABLE_NO_GIT",
        "historical_evidence_scope": "development_only",
        "data_audit": {
            "status": "PASS",
            "financial_rows": 10,
            "report_rows": 20,
            "manifest_path": "manifest.json",
            "manifest_sha256": "m" * 64,
            "coverage": {"passing_months": 60, "months": 95},
        },
        "stage_s": {
            "status": "REJECTED",
            "mean_rank_ic_3m": 0.0,
            "positive_ic_month_share": 0.5,
            "price_momentum_partial_rank_ic": 0.0,
            "hac": {"t_statistic": 0.0, "p_value_two_sided": 1.0},
            "annual_rank_ic": [],
            "component_rank_ic": {},
            "industry_diagnostics": [],
            "gates": {"passes_all": False},
        },
        "stage_p": {"status": "NOT_RUN", "reason": "Stage S failed"},
        "multiple_testing": {"trial_id": 71, "q_value": 1.0},
    }
    path = tmp_path / "report.md"
    write_report(result, path)
    headings = [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("## ")]
    assert len(headings) == 15
    assert headings[0] == "## 1. 继承死亡边界"
    assert headings[-1] == "## 15. 可复算命令、manifest、commit、config hash"


def test_stage_p_reports_cost_stress_and_capacity(tmp_path):
    dates = pd.date_range("2022-01-31", periods=24, freq="ME")
    benchmark = pd.Series(np.tile([0.01, -0.005, 0.015, 0.0], 6), index=dates)
    baseline_gross = benchmark + pd.Series(np.tile([0.001, -0.001, 0.002, 0.0], 6), index=dates)
    candidate_gross = baseline_gross + pd.Series(np.tile([0.002, 0.001, 0.003, -0.001], 6), index=dates)
    baseline = pd.DataFrame(
        {
            "index_code": "000852.SH",
            "signal_date": dates,
            "portfolio_gross_return": baseline_gross.to_numpy(),
            "portfolio_net_return": baseline_gross.to_numpy() - 0.00025,
            "benchmark_return": benchmark.to_numpy(),
            "turnover": 0.5,
            "cost": 0.00025,
        }
    )
    candidate = baseline.copy()
    candidate["portfolio_gross_return"] = candidate_gross.to_numpy()
    candidate["portfolio_net_return"] = candidate_gross.to_numpy() - 0.00025
    candidate["maximum_industry_tilt"] = 0.01
    candidate["industry_tilt_l1"] = 0.10
    candidate["realized_maximum_industry_tilt"] = 0.01
    candidate["realized_industry_tilt_l1"] = 0.10
    candidate["minimum_stock_weight"] = 0.001
    holdings = pd.DataFrame(
        {"index_code": "000852.SH", "signal_date": dates, "ts_code": "A", "weight": 1.0, "trade_weight": 0.01}
    )
    contributions = pd.DataFrame(
        {
            "signal_date": np.repeat(dates, 4),
            "l1_code": np.tile(["I1", "I2", "I3", "I4"], len(dates)),
            "active_return_contribution": 0.001,
        }
    )
    adv_path = tmp_path / "adv.parquet"
    pd.DataFrame({"signal_date": dates, "ts_code": "A", "adv20_cny": 1e9}).to_parquet(adv_path, index=False)
    result = stage_p(candidate, holdings, contributions, baseline, adv_path)
    assert set(result["cost_stress"]) == {"0.0005", "0.001", "0.002"}
    assert result["capacity"]["trades_missing_adv20"] == 0
    assert result["maximum_missing_return_weight"] == 0.0
