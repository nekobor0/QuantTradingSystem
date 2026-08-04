"""Resumable immutable Tushare backfill for F7 financial and analyst data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import tushare as ts

from scripts.alpha_phase1.fetch_tushare_research_data import SlidingWindowRateLimiter


DEFAULT_OUTPUT = Path("artifacts/data_backfill_v7/f7_financials")
FINANCIAL_FIELDS = (
    "ts_code,ann_date,end_date,update_flag,q_sales_yoy,profit_dedt,"
    "q_dtprofit,dt_netprofit_yoy,q_roe"
)
REPORT_FIELDS = (
    "ts_code,name,report_date,report_title,report_type,classify,org_name,"
    "author_name,quarter,np,eps,create_time"
)
DOCUMENTED_REPORT_PAGE_LIMIT = 3000


class WindowRateLimiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self._limit = limit
        self._window = window_seconds
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= self._window:
                    self._calls.popleft()
                if len(self._calls) < self._limit:
                    self._calls.append(now)
                    return
                wait_seconds = self._window - (now - self._calls[0]) + 0.05
            time.sleep(wait_seconds)


class CalendarDayRateLimiter:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._day = None
        self._count = 0

    def acquire(self) -> None:
        while True:
            now = datetime.now().astimezone()
            if self._day != now.date():
                self._day = now.date()
                self._count = 0
            if self._count < self._limit:
                self._count += 1
                return
            tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=now.tzinfo)
            time.sleep(max((tomorrow - now).total_seconds() + 65.0, 65.0))


def rate_limit_delay(message: str, attempt: int) -> float:
    if "次/天" in message:
        now = datetime.now().astimezone()
        tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=now.tzinfo)
        return max((tomorrow - now).total_seconds() + 65.0, 65.0)
    if "次/小时" in message:
        return 3605.0
    if "次/分钟" in message:
        return 65.0
    return float(2 ** (attempt - 1))


def report_page_state(
    rows: int,
    requested_limit: int,
    effective_page_size: int | None,
) -> tuple[int | None, bool]:
    if rows == 0:
        return effective_page_size, True
    if effective_page_size is None:
        if rows in {requested_limit, DOCUMENTED_REPORT_PAGE_LIMIT}:
            effective_page_size = rows
        else:
            return None, True
    return effective_page_size, rows < effective_page_size


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json_atomic(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _owner(output_dir: Path, dataset: str, nonce: str, status: str, **extra: Any) -> None:
    _write_json_atomic(
        {
            "dataset": dataset,
            "pid": os.getpid(),
            "nonce": nonce,
            "status": status,
            "updated_at_utc": _utc_now(),
            **extra,
        },
        output_dir / "owners" / f"{dataset}.json",
    )


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information, False, pid
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return ctypes.get_last_error() == 5
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextmanager
def dataset_lock(output_dir: Path, dataset: str, nonce: str):
    path = output_dir / "locks" / f"{dataset}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dataset": dataset,
        "pid": os.getpid(),
        "nonce": nonce,
        "created_at_utc": _utc_now(),
    }
    for _ in range(3):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                existing_pid = int(existing["pid"])
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"unreadable dataset lock: {path}") from exc
            if _pid_alive(existing_pid):
                raise RuntimeError(
                    f"active dataset lock: {dataset} pid={existing_pid} nonce={existing.get('nonce')}"
                )
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            continue
        else:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            break
    else:
        raise RuntimeError(f"could not acquire dataset lock: {path}")
    try:
        yield payload
    finally:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("pid") == os.getpid() and existing.get("nonce") == nonce:
                path.unlink()
        except FileNotFoundError:
            pass


def lock_snapshot(output_dir: Path, dataset: str) -> dict[str, Any]:
    path = output_dir / "locks" / f"{dataset}.lock"
    if not path.exists():
        return {"exists": False, "path": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        pid = int(payload["pid"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return {"exists": True, "path": str(path), "readable": False, "error": type(exc).__name__}
    return {
        "exists": True,
        "path": str(path),
        "readable": True,
        "pid": pid,
        "nonce": payload.get("nonce"),
        "pid_alive": _pid_alive(pid),
    }


def _write_shard(frame: pd.DataFrame, path: Path, request: dict[str, Any]) -> dict[str, Any]:
    if path.exists():
        raise FileExistsError(f"immutable shard already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)
    metadata = {
        "created_at_utc": _utc_now(),
        "request": request,
        "rows": len(frame),
        "columns": list(frame.columns),
        "sha256": _sha256(path),
    }
    _write_json_atomic(metadata, path.with_suffix(".json"))
    return metadata


def _load_verified_shard(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    sidecar = path.with_suffix(".json")
    if not path.exists() or not sidecar.exists():
        raise FileNotFoundError(f"shard or sidecar missing: {path}")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    if metadata.get("sha256") != _sha256(path):
        raise ValueError(f"shard hash drift: {path}")
    frame = pd.read_parquet(path)
    if int(metadata.get("rows", -1)) != len(frame):
        raise ValueError(f"shard row drift: {path}")
    return frame, metadata


def _load_verified_report_marker(
    marker: Path,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    payload = json.loads(marker.read_text(encoding="utf-8"))
    pages = payload.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError(f"report marker has no pages: {marker}")
    total_rows = 0
    effective_page_size: int | None = None
    expected_offset = 0
    for number, page in enumerate(pages):
        path = Path(page["path"])
        frame, metadata = _load_verified_shard(path)
        _validate_report(frame, start_date, end_date, allow_empty=number > 0)
        if page.get("sha256") != metadata["sha256"] or int(page.get("rows", -1)) != len(frame):
            raise ValueError(f"report marker page drift: {path}")
        request = metadata.get("request", {})
        requested_limit = int(request.get("limit", 0))
        if int(request.get("offset", -1)) != expected_offset or requested_limit <= 0:
            raise ValueError(f"report marker pagination drift: {path}")
        effective_page_size, page_done = report_page_state(
            len(frame), requested_limit, effective_page_size
        )
        if page_done != (number == len(pages) - 1):
            raise ValueError(f"report marker incomplete pagination: {marker}")
        total_rows += len(frame)
        expected_offset += len(frame)
    if int(payload.get("rows", -1)) != total_rows:
        raise ValueError(f"report marker row drift: {marker}")
    return payload


def month_ranges(start_date: str, end_date: str) -> list[tuple[str, str, str]]:
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    if start > end:
        raise ValueError("start_date must not exceed end_date")
    result = []
    for period in pd.period_range(start, end, freq="M"):
        first = max(start, period.start_time).strftime("%Y%m%d")
        last = min(end, period.end_time).strftime("%Y%m%d")
        result.append((period.strftime("%Y%m"), first, last))
    return result


def csi1000_symbols(index_weight_path: Path) -> list[str]:
    frame = pd.read_parquet(index_weight_path, columns=["con_code"])
    return sorted(frame["con_code"].dropna().astype(str).unique())


def _validate_financial(frame: pd.DataFrame, symbol: str) -> None:
    required = set(FINANCIAL_FIELDS.split(","))
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"fina_indicator missing fields: {sorted(missing)}")
    if not frame.empty and set(frame["ts_code"].astype(str)) != {symbol}:
        raise ValueError(f"fina_indicator symbol filter failed for {symbol}")


def _validate_report(frame: pd.DataFrame, start_date: str, end_date: str, *, allow_empty: bool = False) -> None:
    required = set(REPORT_FIELDS.split(","))
    if frame.empty and not allow_empty:
        raise ValueError(f"report_rc returned an empty first page for {start_date}-{end_date}")
    if frame.empty and allow_empty:
        return
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"report_rc missing fields: {sorted(missing)}")
    if frame.empty:
        return
    dates = frame["report_date"].dropna().astype(str)
    if dates.empty or dates.min() < start_date or dates.max() > end_date:
        raise ValueError("report_rc date filter failed")


def _financial_one(
    pro: Any,
    limiter: SlidingWindowRateLimiter,
    output: Path,
    symbol: str,
    start_date: str,
    end_date: str,
    max_attempts: int,
) -> dict[str, Any]:
    path = output / "shards" / "fina_indicator" / f"{symbol.replace('.', '_')}.parquet"
    if path.exists() and path.with_suffix(".json").exists():
        frame, _ = _load_verified_shard(path)
        _validate_financial(frame, symbol)
        return {"symbol": symbol, "status": "cached", "rows": len(frame)}
    request = {
        "api_name": "fina_indicator",
        "ts_code": symbol,
        "start_date": start_date,
        "end_date": end_date,
        "fields": FINANCIAL_FIELDS,
    }
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            limiter.acquire()
            frame = pro.fina_indicator(**{key: value for key, value in request.items() if key != "api_name"})
            _validate_financial(frame, symbol)
            metadata = _write_shard(frame, path, request)
            return {"symbol": symbol, "status": "fetched", "rows": len(frame), "sha256": metadata["sha256"]}
        except Exception as exc:  # Tushare wraps server and network errors inconsistently.
            last_error = exc
            if attempt < max_attempts:
                time.sleep(2 ** (attempt - 1))
    assert last_error is not None
    return {"symbol": symbol, "status": "error", "error_type": type(last_error).__name__, "message": str(last_error)}


def fetch_financials(args: argparse.Namespace, pro: Any, *, nonce: str | None = None) -> dict[str, Any]:
    nonce = nonce or uuid.uuid4().hex
    _owner(args.output_dir, "fina_indicator", nonce, "running", total=0, completed=0)
    symbols = csi1000_symbols(args.index_weight)
    limiter = SlidingWindowRateLimiter(args.financial_calls_per_minute)
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(
                _financial_one,
                pro,
                limiter,
                args.output_dir,
                symbol,
                args.financial_start_date,
                args.end_date,
                args.max_attempts,
            )
            for symbol in symbols
        ]
        for number, future in enumerate(as_completed(futures), 1):
            result = future.result()
            results.append(result)
            if number % 25 == 0 or result["status"] == "error":
                print(json.dumps({"dataset": "fina_indicator", "completed": number, "total": len(symbols), "errors": sum(item["status"] == "error" for item in results)}), flush=True)
                _owner(args.output_dir, "fina_indicator", nonce, "running", total=len(symbols), completed=number, errors=sum(item["status"] == "error" for item in results))
    payload = {
        "generated_at_utc": _utc_now(),
        "dataset": "fina_indicator",
        "symbols": len(symbols),
        "status_counts": pd.Series([item["status"] for item in results]).value_counts().to_dict(),
        "rows": sum(item.get("rows", 0) for item in results),
        "errors": [item for item in results if item["status"] == "error"],
    }
    _write_json_atomic(payload, args.output_dir / "fina_indicator_progress.json")
    _owner(args.output_dir, "fina_indicator", nonce, "completed" if not payload["errors"] else "errors", total=len(symbols), completed=len(results), errors=len(payload["errors"]))
    return payload


def fetch_reports(args: argparse.Namespace, pro: Any, *, nonce: str | None = None) -> dict[str, Any]:
    nonce = nonce or uuid.uuid4().hex
    total_months = len(month_ranges(args.report_start_date, args.end_date))
    _owner(args.output_dir, "report_rc", nonce, "running", total=total_months, completed=0)
    minute_limiter = SlidingWindowRateLimiter(1)
    hourly_limiter = WindowRateLimiter(args.report_calls_per_hour, 3600.0)
    daily_limiter = CalendarDayRateLimiter(args.report_calls_per_day)
    completed = 0
    rows = 0
    for month, start_date, end_date in month_ranges(args.report_start_date, args.end_date):
        marker = args.output_dir / "shards" / "report_rc" / f"{month}.complete.json"
        if marker.exists():
            payload = _load_verified_report_marker(marker, start_date, end_date)
            completed += 1
            rows += int(payload["rows"])
            continue
        offset = 0
        effective_page_size: int | None = None
        month_rows = 0
        pages = []
        while True:
            path = args.output_dir / "shards" / "report_rc" / f"{month}_{offset:06d}.parquet"
            request = {
                "api_name": "report_rc",
                "start_date": start_date,
                "end_date": end_date,
                "limit": args.report_page_size,
                "offset": offset,
                "fields": REPORT_FIELDS,
            }
            if path.exists() and path.with_suffix(".json").exists():
                frame, metadata = _load_verified_shard(path)
                _validate_report(frame, start_date, end_date, allow_empty=offset > 0)
            else:
                last_error: Exception | None = None
                for attempt in range(1, args.max_attempts + 1):
                    try:
                        minute_limiter.acquire()
                        hourly_limiter.acquire()
                        daily_limiter.acquire()
                        frame = pro.report_rc(**{key: value for key, value in request.items() if key != "api_name"})
                        _validate_report(frame, start_date, end_date, allow_empty=offset > 0)
                        break
                    except Exception as exc:  # Tushare wraps rate and transport errors.
                        last_error = exc
                        if attempt < args.max_attempts:
                            delay = rate_limit_delay(str(exc), attempt)
                            print(json.dumps({"dataset": "report_rc", "event": "retry", "attempt": attempt, "delay_seconds": delay, "error": str(exc)}, ensure_ascii=False), flush=True)
                            time.sleep(delay)
                else:
                    assert last_error is not None
                    raise last_error
                metadata = _write_shard(frame, path, request)
            pages.append({"path": str(path), "rows": len(frame), "sha256": metadata["sha256"]})
            month_rows += len(frame)
            effective_page_size, page_done = report_page_state(
                len(frame), args.report_page_size, effective_page_size
            )
            if page_done:
                break
            offset += len(frame)
        marker_payload = {"completed_at_utc": _utc_now(), "month": month, "rows": month_rows, "pages": pages}
        _write_json_atomic(marker_payload, marker)
        completed += 1
        rows += month_rows
        progress = {"generated_at_utc": _utc_now(), "dataset": "report_rc", "completed_months": completed, "total_months": len(month_ranges(args.report_start_date, args.end_date)), "rows": rows, "last_month": month}
        _write_json_atomic(progress, args.output_dir / "report_rc_progress.json")
        _owner(args.output_dir, "report_rc", nonce, "running", total=total_months, completed=completed, rows=rows)
        print(json.dumps(progress), flush=True)
    result = json.loads((args.output_dir / "report_rc_progress.json").read_text(encoding="utf-8"))
    _owner(args.output_dir, "report_rc", nonce, "completed", total=total_months, completed=completed, rows=rows)
    return result


def status(args: argparse.Namespace) -> dict[str, Any]:
    symbols = csi1000_symbols(args.index_weight)
    financial = list((args.output_dir / "shards" / "fina_indicator").glob("*.parquet"))
    target_months = {month for month, _, _ in month_ranges(args.report_start_date, args.end_date)}
    report_root = args.output_dir / "shards" / "report_rc"
    report_markers = [
        path
        for path in report_root.glob("*.complete.json")
        if path.name[:6] in target_months
    ]
    report_pages = [
        path
        for path in report_root.glob("*.parquet")
        if path.name[:6] in target_months
    ]
    report_rows = 0
    for path in report_pages:
        sidecar = path.with_suffix(".json")
        if sidecar.exists():
            report_rows += int(json.loads(sidecar.read_text(encoding="utf-8")).get("rows", 0))
    active_months = sorted({path.name[:6] for path in report_pages}.difference({path.name[:6] for path in report_markers}))
    return {
        "output_dir": str(args.output_dir),
        "financial_shards": len(financial),
        "financial_total": len(symbols),
        "report_months": len(report_markers),
        "report_total_months": len(month_ranges(args.report_start_date, args.end_date)),
        "report_pages": len(report_pages),
        "report_rows": report_rows,
        "report_incomplete_months": active_months,
        "locks": {
            "fina_indicator": lock_snapshot(args.output_dir, "fina_indicator"),
            "report_rc": lock_snapshot(args.output_dir, "report_rc"),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", choices=("status", "financial", "report-rc", "all"), default="status")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--index-weight", type=Path, default=Path("artifacts/alpha_phase1/tushare/index_weight_000852_SH.parquet"))
    parser.add_argument("--financial-start-date", default="20150101")
    parser.add_argument("--report-start-date", default="20180401")
    parser.add_argument("--end-date", default="20260731")
    parser.add_argument("--financial-calls-per-minute", type=int, default=120)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--report-page-size", type=int, default=5000)
    parser.add_argument("--report-calls-per-hour", type=int, default=10)
    parser.add_argument("--report-calls-per-day", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.financial_calls_per_minute <= 200:
        raise ValueError("financial-calls-per-minute must be in [1, 200]")
    if not 1 <= args.workers <= 8:
        raise ValueError("workers must be in [1, 8]")
    if not 1 <= args.report_page_size <= 5000:
        raise ValueError("report-page-size must be in [1, 5000]")
    if not 1 <= args.report_calls_per_hour <= 10:
        raise ValueError("report-calls-per-hour must be in [1, 10]")
    if not 1 <= args.report_calls_per_day <= 10:
        raise ValueError("report-calls-per-day must be in [1, 10]")
    return args


def main() -> None:
    args = parse_args()
    if args.dataset == "status":
        print(json.dumps(status(args), ensure_ascii=False, indent=2))
        return
    pro = ts.pro_api()
    payload: dict[str, Any] = {}
    if args.dataset in {"financial", "all"}:
        nonce = uuid.uuid4().hex
        with dataset_lock(args.output_dir, "fina_indicator", nonce):
            payload["financial"] = fetch_financials(args, pro, nonce=nonce)
        if payload["financial"]["errors"]:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            raise SystemExit(f"financial backfill has {len(payload['financial']['errors'])} errors; rerun to resume")
    if args.dataset in {"report-rc", "all"}:
        nonce = uuid.uuid4().hex
        with dataset_lock(args.output_dir, "report_rc", nonce):
            payload["report_rc"] = fetch_reports(args, pro, nonce=nonce)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
