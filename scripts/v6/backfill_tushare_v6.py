"""Checkpointed Tushare history backfill into isolated V6 staging.

Dry-run/status are network free. Execution requires an explicit phase, writes
request-identified non-empty shards, and never publishes into V5/production.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

import pandas as pd
import tushare as ts

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.alpha_phase1.fetch_tushare_research_data import (
    SlidingWindowRateLimiter,
    load_token,
    write_parquet_atomic,
)


MAX_CALLS_PER_MINUTE = 60
MAX_WORKERS = 2
DEFAULT_OUTPUT = Path("artifacts/data_backfill_v6")
SOURCE_TUSHARE = Path("artifacts/alpha_phase1/tushare")
SUCCESS_STATUSES = {"fetched", "cached"}
HISTORICAL_GAP_ENDS = {
    "daily_basic": "20180701",
    "moneyflow": "20180501",
    "margin_detail": "20180701",
    "stk_limit": "20180701",
    "stock_st": "20180701",
    "financial": "20160313",
    "index_daily": "20180101",
    "index_weight": "20160128",
}
HISTORICAL_DAILY_QUERY_ALIASES = {
    # Tushare stock_basic keeps the retired entity under a T-prefixed code,
    # while daily history is served under the exchange code without T.
    "T600018.SH": "600018.SH",
}


@dataclass(frozen=True, slots=True)
class BackfillTask:
    dataset: str
    key: str
    api_name: str
    params: dict[str, str]
    required_columns: tuple[str, ...]
    page_limit: int | None = None


PHASES: tuple[dict[str, Any], ...] = (
    {"name": "stock_basic_trade_cal", "start": "19901219", "partition": "status/calendar-window", "estimated_tasks": 3, "requires": []},
    {"name": "daily_1990_2004", "start": "19901219", "end": "20041231", "partition": "symbol", "estimated_tasks": 1500, "requires": ["stock_basic"]},
    {"name": "adj_factor", "start": "19901219", "partition": "open-date", "estimated_tasks": 8700, "requires": ["trade_cal"]},
    {"name": "daily_basic", "start": "19901219", "partition": "open-date", "estimated_tasks": 6700, "requires": ["trade_cal"]},
    {"name": "moneyflow", "start": "20100105", "partition": "open-date", "estimated_tasks": 2050, "requires": ["trade_cal"]},
    {"name": "margin_detail", "start": "20100331", "partition": "open-date", "estimated_tasks": 2000, "requires": ["trade_cal"]},
    {"name": "stk_limit", "start": "20070104", "partition": "open-date", "estimated_tasks": 2800, "requires": ["trade_cal"]},
    {"name": "stock_st", "start": "20160101", "partition": "open-date", "estimated_tasks": 610, "requires": ["trade_cal"]},
    {"name": "financial", "start": "19900101", "partition": "symbol/decade", "estimated_tasks": 15000, "requires": ["stock_basic"]},
    {"name": "index", "start": "20020104", "partition": "index/month", "estimated_tasks": 350, "requires": ["trade_cal"]},
    {"name": "event", "start": "19911230", "partition": "month or symbol", "estimated_tasks": 830, "requires": ["stock_basic"]},
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_payload(payload: Any) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_atomic(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(10):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.05)


def assert_staging_root(output_dir: Path, project_root: Path) -> Path:
    root = output_dir if output_dir.is_absolute() else project_root / output_dir
    root = root.resolve()
    allowed = (project_root.resolve() / DEFAULT_OUTPUT).resolve()
    if root != allowed and allowed not in root.parents:
        raise ValueError(f"output must stay under {allowed}")
    return root


def _task(dataset: str, key: str, api_name: str, params: dict[str, str], required: Iterable[str], *, page_limit: int | None = None) -> BackfillTask:
    return BackfillTask(dataset, key, api_name, params, tuple(required), page_limit)


def seed_tasks(end_date: str) -> list[BackfillTask]:
    fields = "ts_code,symbol,name,area,industry,market,list_date,delist_date,list_status"
    tasks = [
        _task("stock_basic", status, "stock_basic", {"exchange": "", "list_status": status, "fields": fields}, ("ts_code", "list_date", "list_status"))
        # Pending-listing securities are not historical data-layer inputs and
        # the endpoint legitimately returns an empty response for this status.
        for status in ("L", "D")
    ]
    tasks.append(_task("trade_cal", f"19901219_{end_date}", "trade_cal", {"exchange": "SSE", "start_date": "19901219", "end_date": end_date}, ("exchange", "cal_date", "is_open", "pretrade_date")))
    return tasks


def load_stock_basic(source_dir: Path) -> pd.DataFrame:
    path = source_dir / "stock_basic.parquet"
    if not path.exists():
        raise FileNotFoundError(f"frozen stock_basic source is missing: {path}")
    return pd.read_parquet(path, columns=["ts_code", "list_date", "delist_date", "list_status"])


def load_staging_calendar(output_dir: Path) -> pd.Series:
    paths = sorted((output_dir / "shards" / "trade_cal").glob("*.parquet"))
    valid = [path for path in paths if _sidecar_path(path).exists()]
    if not valid:
        raise FileNotFoundError("run repaired phase stock_basic_trade_cal before date-partitioned phases")
    frames = [pd.read_parquet(path, columns=["cal_date", "is_open"]) for path in valid]
    calendar = pd.concat(frames, ignore_index=True).drop_duplicates("cal_date")
    return calendar.loc[calendar["is_open"].astype(str).eq("1"), "cal_date"].astype(str).sort_values()


def date_tasks(dataset: str, api_name: str, dates: Iterable[str], required: tuple[str, ...], fields: tuple[str, ...] | None = None) -> list[BackfillTask]:
    tasks = []
    for date in dates:
        params = {"trade_date": date}
        if fields:
            params["fields"] = ",".join(fields)
        tasks.append(_task(dataset, date, api_name, params, required))
    return tasks


def daily_history_tasks(stocks: pd.DataFrame) -> list[BackfillTask]:
    result = []
    for row in stocks.itertuples(index=False):
        start = max("19901219", str(row.list_date))
        end = min("20041231", str(row.delist_date) if pd.notna(row.delist_date) and str(row.delist_date) else "20041231")
        if start <= end:
            target_code = str(row.ts_code)
            query_code = HISTORICAL_DAILY_QUERY_ALIASES.get(target_code, target_code)
            params = {"ts_code": query_code, "start_date": start, "end_date": end, "fields": "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"}
            if query_code != target_code:
                params["_target_ts_code"] = target_code
            result.append(_task("daily_1990_2004", target_code.replace(".", "_"), "daily", params, ("ts_code", "trade_date", "open", "high", "low", "close")))
    return result


def financial_tasks(stocks: pd.DataFrame, end_date: str) -> list[BackfillTask]:
    result = []
    intervals = (("19900101", "19991231"), ("20000101", "20091231"), ("20100101", "20191231"), ("20200101", end_date))
    fields = "ts_code,ann_date,end_date,update_flag,roe,roe_waa,grossprofit_margin,netprofit_margin,ocf_to_or,ocf_to_profit,debt_to_assets,q_sales_yoy,q_profit_yoy"
    for row in stocks.itertuples(index=False):
        for start, end in intervals:
            if start <= end and str(row.list_date) <= end:
                key = f"{str(row.ts_code).replace('.', '_')}_{start[:4]}_{end[:4]}"
                result.append(_task("fina_indicator", key, "fina_indicator", {"ts_code": str(row.ts_code), "start_date": start, "end_date": end, "fields": fields}, ("ts_code", "ann_date", "end_date", "update_flag"), page_limit=100))
    return result


def _months(start: str, end: str) -> list[tuple[str, str, str]]:
    periods = pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq="M")
    return [(period.strftime("%Y%m"), max(period.start_time, pd.Timestamp(start)).strftime("%Y%m%d"), min(period.end_time, pd.Timestamp(end)).strftime("%Y%m%d")) for period in periods]


def index_tasks(calendar: pd.Series, end_date: str) -> list[BackfillTask]:
    tasks = []
    daily_end = min(end_date, HISTORICAL_GAP_ENDS["index_daily"])
    for code, start in (("000300.SH", "20020104"), ("000852.SH", "20041231")):
        if start <= daily_end:
            tasks.append(_task(f"index_daily_{code.replace('.', '_')}", f"{start}_{daily_end}", "index_daily", {"ts_code": code, "start_date": start, "end_date": daily_end}, ("ts_code", "trade_date", "open", "close")))
    starts = {"000300.SH": "20050429", "000905.SH": "20061130", "000852.SH": "20141031"}
    weight_end = min(end_date, HISTORICAL_GAP_ENDS["index_weight"])
    eligible_dates = calendar[calendar <= weight_end]
    month_ends = eligible_dates.groupby(eligible_dates.str[:6]).max().to_dict()
    for code, start in starts.items():
        for month, month_end in month_ends.items():
            if month_end >= start:
                tasks.append(_task(f"index_weight_{code.replace('.', '_')}", month, "index_weight", {"index_code": code, "start_date": f"{month}01", "end_date": month_end}, ("index_code", "con_code", "trade_date", "weight")))
    return tasks


def event_tasks(stocks: pd.DataFrame, end_date: str, source_dir: Path) -> list[BackfillTask]:
    tasks = []
    monthly = (
        ("repurchase", "20001201", "20180701", ("ts_code", "ann_date", "proc"), 2000),
        ("stk_holdertrade", "19940810", "20180701", ("ts_code", "ann_date", "in_de", "change_vol"), 3000),
        ("stk_holdernumber", "19911230", "20180430", ("ts_code", "ann_date", "end_date"), 3000),
    )
    for api, start, local_start_minus_one, required, limit in monthly:
        gap_end = min(end_date, local_start_minus_one)
        for month, first, last in _months(start, gap_end):
            tasks.append(_task(api, month, api, {"start_date": first, "end_date": last}, required, page_limit=limit))
    existing_pledge = source_dir / "shards" / "pledge_detail"
    for row in stocks.itertuples(index=False):
        if not (existing_pledge / f"{row.ts_code}.parquet").exists():
            tasks.append(_task("pledge_detail", str(row.ts_code).replace(".", "_"), "pledge_detail", {"ts_code": str(row.ts_code)}, ("ts_code", "ann_date", "holder_name", "pledge_amount", "start_date", "is_release"), page_limit=1000))
    return tasks


def build_tasks(phase: str, source_dir: Path, output_dir: Path, end_date: str) -> list[BackfillTask]:
    if phase == "stock_basic_trade_cal":
        return seed_tasks(end_date)
    stocks = load_stock_basic(source_dir)
    if phase == "daily_1990_2004":
        return daily_history_tasks(stocks)
    if phase == "financial":
        return financial_tasks(stocks, min(end_date, HISTORICAL_GAP_ENDS["financial"]))
    if phase == "event":
        return event_tasks(stocks, end_date, source_dir)
    calendar = load_staging_calendar(output_dir)
    starts = {item["name"]: item["start"] for item in PHASES}
    effective_end = min(end_date, HISTORICAL_GAP_ENDS.get(phase, end_date))
    dates = calendar[calendar.between(starts[phase], effective_end)].tolist()
    if phase == "adj_factor":
        return date_tasks(phase, phase, dates, ("ts_code", "trade_date", "adj_factor"))
    if phase == "daily_basic":
        fields = ("ts_code", "trade_date", "close", "turnover_rate_f", "volume_ratio", "total_share", "float_share", "free_share", "total_mv", "circ_mv")
        return date_tasks(phase, phase, dates, ("ts_code", "trade_date", "total_mv"), fields)
    if phase == "moneyflow":
        return date_tasks(phase, phase, dates, ("ts_code", "trade_date", "net_mf_amount"))
    if phase == "margin_detail":
        return date_tasks(phase, phase, dates, ("ts_code", "trade_date", "rzye", "rqye"))
    if phase == "stk_limit":
        return date_tasks(phase, phase, dates, ("ts_code", "trade_date", "up_limit", "down_limit"))
    if phase == "stock_st":
        return date_tasks(phase, phase, dates, ("ts_code", "trade_date", "type"))
    if phase == "index":
        return index_tasks(calendar, end_date)
    raise ValueError(f"unknown phase: {phase}")


def request_identity(task: BackfillTask) -> dict[str, Any]:
    return {"api": task.api_name, "params": task.params, "required_schema": list(task.required_columns), "page_limit": task.page_limit}


def request_hash(task: BackfillTask) -> str:
    return _hash_payload(request_identity(task))


def _sidecar_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".request.json")


def _date_bounds(frame: pd.DataFrame) -> dict[str, dict[str, str | None]]:
    result: dict[str, dict[str, str | None]] = {}
    for column in ("trade_date", "cal_date", "ann_date", "end_date"):
        if column in frame.columns:
            values = frame[column].dropna().astype(str)
            result[column] = {"min": values.min() if not values.empty else None, "max": values.max() if not values.empty else None}
    return result


def _validate_frame_contract(frame: pd.DataFrame, task: BackfillTask) -> None:
    missing = set(task.required_columns) - set(frame.columns)
    if missing:
        raise ValueError(f"{task.api_name} missing columns: {sorted(missing)}")
    if task.dataset == "daily_1990_2004":
        extra = {"vol", "amount"}.difference(frame.columns)
        if extra:
            raise ValueError(f"daily history missing columns: {sorted(extra)}")
    for column, parameter in (("ts_code", "ts_code"), ("index_code", "index_code")):
        expected = task.params.get(parameter)
        if expected and column in frame.columns and not frame[column].astype(str).eq(expected).all():
            raise ValueError(f"{task.api_name} returned rows outside requested {parameter}={expected}")
    if "trade_date" in frame.columns:
        dates = frame["trade_date"].astype(str)
        exact = task.params.get("trade_date")
        if exact and not dates.eq(exact).all():
            raise ValueError(f"{task.api_name} returned rows outside trade_date={exact}")
        start = task.params.get("start_date")
        end = task.params.get("end_date")
        if start and dates.lt(start).any() or end and dates.gt(end).any():
            raise ValueError(f"{task.api_name} returned trade_date outside request bounds")
    primary_keys = {
        "daily_1990_2004": ["ts_code", "trade_date"],
        "adj_factor": ["ts_code", "trade_date"],
        "daily_basic": ["ts_code", "trade_date"],
        "moneyflow": ["ts_code", "trade_date"],
        "margin_detail": ["ts_code", "trade_date"],
        "stk_limit": ["ts_code", "trade_date"],
        "stock_st": ["ts_code", "trade_date", "type"],
        "trade_cal": ["exchange", "cal_date"],
        "stock_basic": ["ts_code"],
    }.get(task.dataset)
    if primary_keys and frame.duplicated(primary_keys).any():
        raise ValueError(f"{task.api_name} returned duplicate primary keys")


def _validate_cached(path: Path, task: BackfillTask) -> dict[str, Any]:
    sidecar_path = _sidecar_path(path)
    if not sidecar_path.exists():
        raise ValueError(f"legacy cache has no request identity sidecar: {path}")
    metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
    expected_hash = request_hash(task)
    if metadata.get("request_hash") != expected_hash or metadata.get("request") != request_identity(task):
        raise ValueError(f"cached request identity mismatch: {path}")
    if metadata.get("content_hash") != _hash_file(path):
        raise ValueError(f"cached content hash mismatch: {path}")
    frame = pd.read_parquet(path)
    _validate_frame_contract(frame, task)
    if frame.empty:
        raise ValueError(f"cached shard is empty: {path}")
    if metadata.get("rows") != len(frame) or metadata.get("schema") != list(frame.columns) or metadata.get("date_bounds") != _date_bounds(frame):
        raise ValueError(f"cached shard metadata mismatch: {path}")
    return metadata


def _retryable(error: Exception) -> bool:
    message = str(error).lower()
    terminal = ("权限", "permission", "积分", "必填", "parameter", "字段", "unknown api")
    return not any(token in message for token in terminal)


def _result_base(task: BackfillTask, path: Path) -> dict[str, Any]:
    return {
        "task": asdict(task),
        "request_hash": request_hash(task),
        "path": path.as_posix(),
        "rows": None,
        "content_hash": None,
        "schema": None,
        "date_bounds": {},
    }


def fetch_task(client: Any, task: BackfillTask, output_dir: Path, limiter: SlidingWindowRateLimiter, max_attempts: int) -> dict[str, Any]:
    path = output_dir / "shards" / task.dataset / f"{task.key}.parquet"
    base = _result_base(task, path)
    if path.exists() or _sidecar_path(path).exists():
        try:
            metadata = _validate_cached(path, task)
            return {**base, "status": "cached", **{key: metadata[key] for key in ("rows", "content_hash", "schema", "date_bounds")}}
        except Exception as error:
            return {**base, "status": "cache_invalid", "error_type": type(error).__name__, "message": str(error)}
    pages: list[pd.DataFrame] = []
    offset = 0
    attempts_total = 0
    while True:
        pagination_complete = False
        for attempt in range(1, max_attempts + 1):
            attempts_total += 1
            try:
                limiter.acquire()
                params: dict[str, Any] = {
                    key: value for key, value in task.params.items() if not key.startswith("_")
                }
                if task.page_limit is not None:
                    params.update(limit=task.page_limit, offset=offset)
                frame = client.query(task.api_name, **params)
                if frame.empty:
                    if pages:
                        pagination_complete = True
                        break
                    if attempt < max_attempts:
                        time.sleep(2 ** (attempt - 1))
                        continue
                    return {**base, "status": "source_empty", "attempts": attempts_total, "rows": 0, "message": f"{task.api_name} returned an empty response at offset {offset}"}
                missing = set(task.required_columns) - set(frame.columns)
                if missing:
                    raise ValueError(f"{task.api_name} missing columns: {sorted(missing)}")
                pages.append(frame)
                break
            except Exception as error:  # SDK transport errors are not consistently typed.
                if not _retryable(error) or attempt == max_attempts:
                    return {**base, "status": "error", "attempts": attempts_total, "error_type": type(error).__name__, "message": str(error)}
                time.sleep(2 ** (attempt - 1))
        if pagination_complete:
            break
        if task.page_limit is None or len(pages[-1]) < task.page_limit:
            break
        offset += task.page_limit
    combined = pd.concat(pages, ignore_index=True).drop_duplicates()
    if combined.empty:
        return {**base, "status": "source_empty", "attempts": attempts_total, "rows": 0, "message": "deduplicated response is empty"}
    _validate_frame_contract(combined, task)
    write_parquet_atomic(combined, path)
    metadata = {
        "version": 1,
        "request": request_identity(task),
        "request_hash": request_hash(task),
        "content_hash": _hash_file(path),
        "rows": len(combined),
        "schema": list(combined.columns),
        "date_bounds": _date_bounds(combined),
        "written_at_utc": _utc_now(),
    }
    write_json_atomic(metadata, _sidecar_path(path))
    return {**base, "status": "fetched", "attempts": attempts_total, **{key: metadata[key] for key in ("rows", "content_hash", "schema", "date_bounds")}}


def _source_manifest(phase: str, source_dir: Path, output_dir: Path) -> dict[str, Any]:
    paths: list[Path] = []
    if phase != "stock_basic_trade_cal":
        stock = source_dir / "stock_basic.parquet"
        if stock.exists():
            paths.append(stock)
    if phase not in {"stock_basic_trade_cal", "daily_1990_2004", "financial", "event"}:
        paths.extend(sorted((output_dir / "shards" / "trade_cal").glob("*.parquet")))
    files = [{"path": path.as_posix(), "sha256": _hash_file(path)} for path in paths]
    return {"files": files, "source_hash": _hash_payload(files)}


def _checkpoint_payload(phase: str, end_date: str, tasks: list[BackfillTask], output_dir: Path, source: dict[str, Any], calls_per_minute: int, workers: int, max_attempts: int, request_timeout: int = 30) -> dict[str, Any]:
    requests = [request_hash(task) for task in tasks]
    return {
        "version": 2,
        "state": "RUNNING",
        "started_at_utc": _utc_now(),
        "updated_at_utc": _utc_now(),
        "phase": phase,
        "end_date": end_date,
        "output_dir": output_dir.as_posix(),
        "source": source,
        "calls_per_minute": calls_per_minute,
        "workers": workers,
        "max_attempts": max_attempts,
        "request_timeout_seconds": request_timeout,
        "task_count": len(tasks),
        "request_set_hash": _hash_payload(requests),
        "publication": "STAGING_ONLY",
        "token_persisted": False,
        "counts": {},
        "results": [],
    }


def _update_checkpoint(checkpoint: dict[str, Any], path: Path, result: dict[str, Any] | None = None, state: str | None = None) -> None:
    if result is not None:
        checkpoint["results"].append(result)
    counts: dict[str, int] = {}
    for item in checkpoint["results"]:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    checkpoint["counts"] = counts
    checkpoint["updated_at_utc"] = _utc_now()
    if state is not None:
        checkpoint["state"] = state
    write_json_atomic(checkpoint, path)


def run_tasks(tasks: list[BackfillTask], output_dir: Path, token: str, calls_per_minute: int, workers: int, max_attempts: int, *, checkpoint: dict[str, Any], checkpoint_path: Path, request_timeout: int = 30, client: Any | None = None) -> list[dict[str, Any]]:
    _update_checkpoint(checkpoint, checkpoint_path)
    api_client = client if client is not None else ts.pro_api(token, timeout=request_timeout)
    limiter = SlidingWindowRateLimiter(calls_per_minute)
    results: list[dict[str, Any]] = []
    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(fetch_task, api_client, task, output_dir, limiter, max_attempts) for task in tasks]
            for number, future in enumerate(as_completed(futures), start=1):
                result = future.result()
                results.append(result)
                checkpoint["results"].append(result)
                status = result["status"]
                checkpoint["counts"][status] = checkpoint["counts"].get(status, 0) + 1
                checkpoint["updated_at_utc"] = _utc_now()
                if number % 25 == 0 or result["status"] not in SUCCESS_STATUSES:
                    write_json_atomic(checkpoint, checkpoint_path)
                    print(json.dumps({"event": "v6_backfill_progress", "completed": number, "total": len(tasks), "counts": checkpoint["counts"]}), flush=True)
        final_state = "COMPLETED" if len(results) == len(tasks) and all(item["status"] in SUCCESS_STATUSES for item in results) else "INCOMPLETE"
        _update_checkpoint(checkpoint, checkpoint_path, state=final_state)
        return results
    except BaseException:
        _update_checkpoint(checkpoint, checkpoint_path, state="FAILED")
        raise


def _global_staging_root(project_root: Path) -> Path:
    return (project_root.resolve() / DEFAULT_OUTPUT).resolve()


@contextmanager
def staging_lock(project_root: Path, phase: str) -> Iterator[dict[str, Any]]:
    lock_path = _global_staging_root(project_root) / ".backfill.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    owner = {"pid": os.getpid(), "phase": phase, "started_at_utc": _utc_now(), "nonce": uuid.uuid4().hex}
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        existing = lock_path.read_text(encoding="utf-8", errors="replace")
        raise RuntimeError(f"another V6 backfill owns {lock_path}: {existing}") from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(owner, handle, ensure_ascii=False)
        yield owner
    finally:
        try:
            current = json.loads(lock_path.read_text(encoding="utf-8"))
            if current.get("nonce") == owner["nonce"]:
                lock_path.unlink()
        except FileNotFoundError:
            pass


def status(output_dir: Path, project_root: Path | None = None) -> dict[str, Any]:
    datasets = []
    total_legacy = 0
    shard_root = output_dir / "shards"
    if shard_root.exists():
        for directory in sorted(path for path in shard_root.iterdir() if path.is_dir()):
            paths = list(directory.glob("*.parquet"))
            sidecars = list(directory.glob("*.parquet.request.json"))
            legacy = sum(not _sidecar_path(path).exists() for path in paths)
            orphan = sum(not Path(str(sidecar)[: -len(".request.json")]).exists() for sidecar in sidecars)
            total_legacy += legacy
            datasets.append({"dataset": directory.name, "shards": len(paths), "identified_shards": len(paths) - legacy, "legacy_shards": legacy, "orphan_sidecars": orphan, "bytes": sum(path.stat().st_size for path in paths)})
    checkpoint_states: dict[str, int] = {}
    checkpoint_dir = output_dir / "checkpoints"
    if checkpoint_dir.exists():
        for path in checkpoint_dir.glob("*.json"):
            try:
                state = json.loads(path.read_text(encoding="utf-8")).get("state", "UNKNOWN")
            except (OSError, json.JSONDecodeError):
                state = "INVALID"
            checkpoint_states[state] = checkpoint_states.get(state, 0) + 1
    root = _global_staging_root(project_root) if project_root is not None else output_dir
    lock_path = root / ".backfill.lock"
    lock_owner: Any = None
    if lock_path.exists():
        try:
            lock_owner = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            lock_owner = {"invalid": True}
    return {"status": "STAGING_STATUS", "output_dir": output_dir.as_posix(), "datasets": datasets, "checkpoint_states": checkpoint_states, "lock": {"active": lock_path.exists(), "owner": lock_owner}, "legacy_shards": total_legacy, "safe_to_resume": total_legacy == 0 and not lock_path.exists()}


def dry_run(phase: str, output_dir: Path, source_dir: Path, end_date: str) -> dict[str, Any]:
    if phase == "all":
        return {"status": "DRY_RUN", "network": False, "output_dir": output_dir.as_posix(), "max_calls_per_minute": MAX_CALLS_PER_MINUTE, "phases": list(PHASES)}
    try:
        tasks = build_tasks(phase, source_dir, output_dir, end_date)
        return {"status": "DRY_RUN", "network": False, "phase": phase, "tasks": len(tasks), "sample": [asdict(task) for task in tasks[:3]]}
    except FileNotFoundError as error:
        spec = next(item for item in PHASES if item["name"] == phase)
        return {"status": "DRY_RUN", "network": False, "phase": phase, "tasks_estimated": spec["estimated_tasks"], "blocked_until": str(error)}


def validate_end_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise argparse.ArgumentTypeError("end-date must be a real date in YYYYMMDD format") from error
    if parsed.strftime("%Y%m%d") != value or value < "19901219":
        raise argparse.ArgumentTypeError("end-date must be YYYYMMDD and not earlier than 19901219")
    return value


def bounded_int(name: str, minimum: int, maximum: int):
    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError as error:
            raise argparse.ArgumentTypeError(f"{name} must be an integer") from error
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(f"{name} must be between {minimum} and {maximum}")
        return number
    return parse


def main() -> None:
    names = [item["name"] for item in PHASES]
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-tushare-dir", type=Path, default=SOURCE_TUSHARE)
    parser.add_argument("--phase", choices=["all", *names], default="all")
    parser.add_argument("--end-date", type=validate_end_date, default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--config", type=Path)
    parser.add_argument("--calls-per-minute", type=bounded_int("calls-per-minute", 1, MAX_CALLS_PER_MINUTE), default=60)
    parser.add_argument("--workers", type=bounded_int("workers", 1, MAX_WORKERS), default=2)
    parser.add_argument("--max-attempts", type=bounded_int("max-attempts", 1, 10), default=3)
    parser.add_argument("--request-timeout", type=bounded_int("request-timeout", 5, 60), default=15)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--status", action="store_true")
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    output_dir = assert_staging_root(args.output_dir, project_root)
    source_dir = args.source_tushare_dir if args.source_tushare_dir.is_absolute() else project_root / args.source_tushare_dir
    if args.status:
        print(json.dumps(status(output_dir, project_root), ensure_ascii=False, indent=2))
        return
    if not args.execute:
        print(json.dumps(dry_run(args.phase, output_dir, source_dir, args.end_date), ensure_ascii=False, indent=2))
        return
    if args.phase == "all":
        parser.error("--execute requires one explicit phase; phases are checkpoint boundaries")
    tasks = build_tasks(args.phase, source_dir, output_dir, args.end_date)
    source = _source_manifest(args.phase, source_dir, output_dir)
    checkpoint = _checkpoint_payload(args.phase, args.end_date, tasks, output_dir, source, args.calls_per_minute, args.workers, args.max_attempts, args.request_timeout)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    checkpoint_path = output_dir / "checkpoints" / f"{args.phase}_{stamp}.json"
    with staging_lock(project_root, args.phase):
        _update_checkpoint(checkpoint, checkpoint_path)
        try:
            results = run_tasks(tasks, output_dir, load_token(args.config), args.calls_per_minute, args.workers, args.max_attempts, checkpoint=checkpoint, checkpoint_path=checkpoint_path, request_timeout=args.request_timeout)
        except BaseException:
            if checkpoint["state"] == "RUNNING":
                _update_checkpoint(checkpoint, checkpoint_path, state="FAILED")
            raise
    summary = {"phase": args.phase, "tasks": len(tasks), "state": checkpoint["state"], "counts": checkpoint["counts"], "checkpoint": checkpoint_path.as_posix(), "publication": "STAGING_ONLY"}
    print(json.dumps(summary, ensure_ascii=False))
    if checkpoint["state"] != "COMPLETED":
        raise SystemExit("phase incomplete; inspect checkpoint and rerun into a clean identified staging root")


if __name__ == "__main__":
    main()
