"""Audit V6 Tushare history coverage without making network requests."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


ENDPOINTS: tuple[dict[str, Any], ...] = (
    {"api": "stock_basic", "earliest": "19901201", "evidence": "local list_date", "points": 2000, "limit": 6000, "url": "https://tushare.pro/document/1?doc_id=25"},
    {"api": "trade_cal", "earliest": "19901219", "evidence": "account smoke", "points": 2000, "limit": None, "url": "https://tushare.pro/document/2?doc_id=26"},
    {"api": "daily", "earliest": "19901219", "evidence": "account smoke: 600601.SH", "points": 120, "limit": 6000, "url": "https://tushare.pro/document/2?doc_id=27"},
    {"api": "adj_factor", "earliest": "19901219", "evidence": "account smoke: 600601.SH", "points": 2000, "limit": None, "url": "https://tushare.pro/document/2?doc_id=28"},
    {"api": "daily_basic", "earliest": "19901219", "evidence": "account smoke: 600601.SH", "points": 2000, "limit": 6000, "url": "https://tushare.pro/document/2?doc_id=32"},
    {"api": "fina_indicator", "earliest": "19900630", "evidence": "account smoke: report period", "points": 2000, "limit": 100, "url": "https://tushare.pro/document/2?doc_id=79"},
    {"api": "index_daily:000300.SH", "earliest": "20020104", "evidence": "account smoke", "points": 2000, "limit": None, "url": "https://tushare.pro/document/2?doc_id=95"},
    {"api": "index_daily:000852.SH", "earliest": "20041231", "evidence": "account smoke", "points": 2000, "limit": None, "url": "https://tushare.pro/document/2?doc_id=95"},
    {"api": "index_weight:000300.SH", "earliest": "20050429", "evidence": "account smoke", "points": 2000, "limit": None, "url": "https://tushare.pro/document/2?doc_id=96"},
    {"api": "index_weight:000905.SH", "earliest": "20061130", "evidence": "account smoke", "points": 2000, "limit": None, "url": "https://tushare.pro/document/2?doc_id=96"},
    {"api": "index_weight:000852.SH", "earliest": "20141031", "evidence": "account smoke", "points": 2000, "limit": None, "url": "https://tushare.pro/document/2?doc_id=96"},
    {"api": "index_member_all", "earliest": None, "evidence": "official documentation has no start date", "points": 2000, "limit": 2000, "url": "https://tushare.pro/document/2?doc_id=335"},
    {"api": "stk_limit", "earliest": "20070104", "evidence": "account smoke: 600601.SH", "points": 2000, "limit": 5800, "url": "https://tushare.pro/document/2?doc_id=183"},
    {"api": "moneyflow", "earliest": "20100105", "evidence": "official: 2010; account smoke exact date", "points": 2000, "limit": 6000, "url": "https://tushare.pro/document/2?doc_id=170"},
    {"api": "margin_detail", "earliest": "20100331", "evidence": "account smoke: 41 rows; prior day empty", "points": 2000, "limit": 6000, "url": "https://tushare.pro/document/2?doc_id=59"},
    {"api": "stock_st", "earliest": "20160101", "evidence": "official explicit start", "points": 3000, "limit": 1000, "url": "https://tushare.pro/document/2?doc_id=397"},
    {"api": "stk_holdernumber", "earliest": "19911230", "evidence": "account smoke", "points": 600, "limit": 3000, "url": "https://tushare.pro/document/2?doc_id=166"},
    {"api": "stk_holdertrade", "earliest": "19940810", "evidence": "account smoke", "points": 2000, "limit": 3000, "url": "https://tushare.pro/document/2?doc_id=175"},
    {"api": "repurchase", "earliest": "20001201", "evidence": "account smoke", "points": 2000, "limit": 2000, "url": "https://tushare.pro/document/2?doc_id=124"},
    {"api": "pledge_detail", "earliest": "20030402", "evidence": "account smoke and local shards", "points": 2000, "limit": 1000, "url": "https://tushare.pro/document/2?doc_id=111"},
)


LOCAL_DATASETS: tuple[dict[str, Any], ...] = (
    {"dataset": "stock_basic", "file": "stock_basic.parquet", "date": "list_date", "pk": ["ts_code"], "api": "stock_basic"},
    {"dataset": "trade_cal", "file": "trade_cal.parquet", "date": "cal_date", "pk": ["exchange", "cal_date"], "api": "trade_cal"},
    {"dataset": "daily_basic_full", "file": "daily_basic_full.parquet", "date": "trade_date", "pk": ["ts_code", "trade_date"], "api": "daily_basic"},
    {"dataset": "daily_basic_month_end", "file": "daily_basic_month_end.parquet", "date": "trade_date", "pk": ["ts_code", "trade_date"], "api": "daily_basic"},
    {"dataset": "daily_valuation_month_end", "file": "daily_valuation_month_end.parquet", "date": "trade_date", "pk": ["ts_code", "trade_date"], "api": "daily_basic"},
    {"dataset": "moneyflow", "file": "moneyflow.parquet", "date": "trade_date", "pk": ["ts_code", "trade_date"], "api": "moneyflow"},
    {"dataset": "margin_detail", "file": "margin_detail.parquet", "date": "trade_date", "pk": ["ts_code", "trade_date"], "api": "margin_detail"},
    {"dataset": "stk_limit_full", "file": "stk_limit_full.parquet", "date": "trade_date", "pk": ["ts_code", "trade_date"], "api": "stk_limit"},
    {"dataset": "stock_st_full_available", "file": "stock_st_full_available.parquet", "date": "trade_date", "pk": ["ts_code", "trade_date"], "api": "stock_st"},
    {"dataset": "fina_indicator", "file": "fina_indicator.parquet", "date": "ann_date", "pk": ["ts_code", "end_date", "ann_date", "update_flag"], "api": "fina_indicator"},
    {"dataset": "index_daily_000300_SH", "file": "index_daily_000300_SH.parquet", "date": "trade_date", "pk": ["ts_code", "trade_date"], "api": "index_daily:000300.SH"},
    {"dataset": "index_daily_000852_SH", "file": "index_daily_000852_SH.parquet", "date": "trade_date", "pk": ["ts_code", "trade_date"], "api": "index_daily:000852.SH"},
    {"dataset": "index_weight_000300_SH", "file": "index_weight_000300_SH.parquet", "date": "trade_date", "pk": ["index_code", "con_code", "trade_date"], "api": "index_weight:000300.SH"},
    {"dataset": "index_weight_000905_SH", "file": "index_weight_000905_SH.parquet", "date": "trade_date", "pk": ["index_code", "con_code", "trade_date"], "api": "index_weight:000905.SH"},
    {"dataset": "index_weight_000852_SH", "file": "index_weight_000852_SH.parquet", "date": "trade_date", "pk": ["index_code", "con_code", "trade_date"], "api": "index_weight:000852.SH"},
    {"dataset": "index_members_sw2021", "file": "index_members_sw2021.parquet", "date": "in_date", "pk": ["l1_code", "ts_code", "in_date", "out_date", "is_new"], "api": "index_member_all"},
    {"dataset": "repurchase", "file": "repurchase.parquet", "date": "ann_date", "pk": ["event_fields", "row_hash"], "api": "repurchase"},
    {"dataset": "stk_holdernumber", "file": "stk_holdernumber.parquet", "date": "ann_date", "pk": ["ts_code", "ann_date", "end_date"], "api": "stk_holdernumber"},
    {"dataset": "stk_holdertrade", "file": "stk_holdertrade.parquet", "date": "ann_date", "pk": ["event_fields", "row_hash"], "api": "stk_holdertrade"},
    {"dataset": "delisted_daily", "file": "delisted_daily.parquet", "date": "trade_date", "pk": ["ts_code", "trade_date"], "api": "daily"},
    {"dataset": "delisted_adj_factor", "file": "delisted_adj_factor.parquet", "date": "trade_date", "pk": ["ts_code", "trade_date"], "api": "adj_factor"},
)


ESTIMATED_BACKFILL_ROWS = {
    "production_daily_1990_2004": 2_250_000,
    "daily_basic_pre_2018": 9_470_000,
    "adj_factor_pre_2018": 9_470_000,
    "moneyflow_pre_2018": 5_000_000,
    "margin_detail_pre_2018": {"low": 1_200_000, "high": 1_600_000},
    "stk_limit_pre_2018": 7_000_000,
    "stock_st_pre_2018": {"low": 30_000, "high": 80_000},
    "fina_indicator_pre_2016": {"low": 150_000, "high": 200_000},
    "month_end_valuation_pre_2016": 450_000,
    "three_index_weight_pre_2016": 100_000,
}


def _column_range(metadata: pq.FileMetaData, name: str) -> tuple[str | None, str | None]:
    index = metadata.schema.names.index(name) if name in metadata.schema.names else -1
    values: list[str] = []
    if index >= 0:
        for row_group in range(metadata.num_row_groups):
            statistics = metadata.row_group(row_group).column(index).statistics
            if statistics is not None and statistics.has_min_max:
                values.extend((str(statistics.min), str(statistics.max)))
    return (min(values), max(values)) if values else (None, None)


def parquet_summary(path: Path, date_column: str) -> dict[str, Any]:
    metadata = pq.ParquetFile(path).metadata
    start, end = _column_range(metadata, date_column)
    return {
        "path": path.as_posix(),
        "rows": metadata.num_rows,
        "columns": metadata.schema.names,
        "date_column": date_column,
        "date_min": start,
        "date_max": end,
    }


def pledge_summary(root: Path) -> dict[str, Any]:
    paths = sorted((root / "shards" / "pledge_detail").glob("*.parquet"))
    rows = 0
    nonempty = 0
    starts: list[str] = []
    ends: list[str] = []
    for path in paths:
        metadata = pq.ParquetFile(path).metadata
        rows += metadata.num_rows
        nonempty += metadata.num_rows > 0
        start, end = _column_range(metadata, "ann_date")
        if start:
            starts.append(start)
        if end:
            ends.append(end)
    return {
        "path": (root / "shards" / "pledge_detail").as_posix(),
        "files": len(paths),
        "expected_files": 5872,
        "nonempty_files": nonempty,
        "rows": rows,
        "date_column": "ann_date",
        "date_min": min(starts) if starts else None,
        "date_max": max(ends) if ends else None,
        "complete": len(paths) == 5872,
        "primary_key": ["ts_code", "ann_date", "holder_name", "start_date", "pledge_amount", "is_release", "release_date"],
    }


def build_audit(tushare_dir: Path) -> dict[str, Any]:
    endpoint_by_name = {item["api"]: item for item in ENDPOINTS}
    local: list[dict[str, Any]] = []
    for spec in LOCAL_DATASETS:
        path = tushare_dir / spec["file"]
        if not path.exists():
            local.append({**spec, "path": path.as_posix(), "exists": False})
            continue
        summary = parquet_summary(path, spec["date"])
        official_start = endpoint_by_name[spec["api"]]["earliest"]
        local.append(
            {
                **spec,
                **summary,
                "exists": True,
                "official_or_verified_start": official_start,
                "history_gap": bool(official_start and summary["date_min"] and summary["date_min"] > official_start),
            }
        )
    pledge = pledge_summary(tushare_dir)
    anomalies = [
        {"dataset": "stock_st_full_available", "severity": "BLOCK", "finding": "18 source-gap dates are excluded; empty API responses must not mean no ST stocks"},
        {"dataset": "index_members_sw2021", "severity": "WARN", "finding": "in_date reaches 19840509, before the A-share market; validate or quarantine"},
        {"dataset": "stk_holdernumber", "severity": "WARN", "finding": "end_date contains implausible 1900 and 2053 values; apply range checks"},
        {"dataset": "pledge_detail", "severity": "BLOCK" if not pledge["complete"] else "PASS", "finding": f"{pledge['files']}/{pledge['expected_files']} immutable symbol shards exist; no completed aggregate manifest"},
        {"dataset": "fina_indicator", "severity": "WARN", "finding": "retain announcement date and update_flag; period_end alone is not a PIT/version key"},
    ]
    return {
        "version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Tushare interfaces already used by alpha_phase1; read-only audit",
        "account_policy": {
            "points": 3000,
            "documented_calls_per_minute": 200,
            "documented_daily_calls_per_api": 100000,
            "v6_branch_max_calls_per_minute": 60,
            "url": "https://tushare.pro/document/1?doc_id=290",
        },
        "endpoints": list(ENDPOINTS),
        "local_datasets": local,
        "pledge_detail_shards": pledge,
        "estimated_backfill_rows": ESTIMATED_BACKFILL_ROWS,
        "anomalies": anomalies,
        "production_data_layer": {
            "known_snapshot": {"a_share_instruments": 5533, "daily_bars": 16342981, "daily_bar_start": "20050104", "daily_bar_end": "20260728", "adjustment_factors": 0, "classification_memberships": 0, "universe_memberships": 0},
            "directly_mappable": ["stock_basic", "trade_cal", "daily", "adj_factor", "stock_st", "fina_indicator", "index_member_all", "index_weight"],
            "schema_blocked": ["daily_basic", "moneyflow", "margin_detail", "stk_limit", "stk_holdernumber", "stk_holdertrade", "repurchase", "pledge_detail"],
            "rule": "Stage first. Do not publish research-only datasets without canonical facts, version keys, availability timestamps, and lineage.",
        },
        "concurrency": {
            "decision": "SAFE_ONLY_WITH_ISOLATED_STAGING",
            "v6_reads": "artifacts/alpha_phase1/** frozen manifests",
            "backfill_writes": "artifacts/data_backfill_v6/** only",
            "conflicts": ["shared Tushare account quota", "overwriting V5 aggregates or manifests", "changing source hashes while V6 evaluates"],
            "publication_gate": "Aggregate and publish only in a V6 compute window after data-quality review.",
        },
    }


def markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# Tushare历史覆盖审计（V6）",
        "",
        f"生成时间：`{audit['generated_at_utc']}`",
        "",
        "结论：支线只能写入独立 `artifacts/data_backfill_v6/**` staging。不得覆盖V5资产；与V6共享账号时限速不超过60次/分。",
        "",
        "## 接口自然起点、权限和单次限制",
        "",
        "| 接口 | 最早日期 | 证据 | 积分 | 单次上限 |",
        "|---|---:|---|---:|---:|",
    ]
    for item in audit["endpoints"]:
        lines.append(f"| `{item['api']}` | {item['earliest'] or '未声明'} | {item['evidence']} | {item['points']} | {item['limit'] or '未声明'} |")
    lines.extend(["", "## 本地资产", "", "| 数据集 | 行数 | 本地范围 | 主键/版本键 | 是否有历史缺口 |", "|---|---:|---|---|---|"])
    for item in audit["local_datasets"]:
        if not item["exists"]:
            lines.append(f"| `{item['dataset']}` | - | 缺文件 | `{','.join(item['pk'])}` | 是 |")
            continue
        lines.append(f"| `{item['dataset']}` | {item['rows']:,} | {item['date_min']}..{item['date_max']} | `{','.join(item['pk'])}` | {'是' if item['history_gap'] else '否'} |")
    pledge = audit["pledge_detail_shards"]
    lines.append(f"| `pledge_detail_shards` | {pledge['rows']:,} | {pledge['date_min']}..{pledge['date_max']} | composite | {'否' if pledge['complete'] else '未完成'} |")
    lines.extend(["", "## 异常和发布门禁", ""])
    lines.extend(f"- **{item['severity']}** `{item['dataset']}`：{item['finding']}" for item in audit["anomalies"])
    lines.extend([
        "",
        "## 与V6冲突结论",
        "",
        "- 只读审计和独立staging可并行。",
        "- 不得并行改写 `artifacts/alpha_phase1/tushare` 聚合文件或manifest。",
        "- 回填支线限制为60次/分；未统一限流时不得同时启动其他Tushare抓取器。",
        "- 生产行情只缺1990—2004约225万行；2005年后应与TDX对账，不应重复灌库。",
        "- 无规范事实表的数据保留在staging，完成schema、PIT和lineage设计后再发布。",
        "",
    ])
    return "\n".join(lines)


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tushare-dir", type=Path, default=Path("artifacts/alpha_phase1/tushare"))
    parser.add_argument("--json-output", type=Path, default=Path("artifacts/data_audits/tushare_history_v6.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("artifacts/data_audits/tushare_history_v6.md"))
    args = parser.parse_args()
    audit = build_audit(args.tushare_dir)
    write_atomic(args.json_output, json.dumps(audit, ensure_ascii=False, indent=2))
    write_atomic(args.markdown_output, markdown(audit))
    print(json.dumps({"status": "PASS", "datasets": len(audit["local_datasets"]), "anomalies": len(audit["anomalies"])}))


if __name__ == "__main__":
    main()
