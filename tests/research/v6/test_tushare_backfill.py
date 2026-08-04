from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts.v6 import backfill_tushare_v6 as module


class _Limiter:
    calls = 0

    def acquire(self) -> None:
        self.calls += 1


def test_atomic_checkpoint_retries_transient_windows_reader_lock(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "checkpoint.json"
    real_replace = module.os.replace
    attempts = 0

    def flaky_replace(source, target) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("transient Windows reader lock")
        real_replace(source, target)

    monkeypatch.setattr(module.os, "replace", flaky_replace)
    module.write_json_atomic({"state": "RUNNING"}, destination)

    assert attempts == 3
    assert json.loads(destination.read_text(encoding="utf-8")) == {"state": "RUNNING"}
    assert not destination.with_suffix(".json.tmp").exists()


def test_default_dry_run_lists_all_isolated_phases(tmp_path) -> None:
    output = tmp_path / "artifacts" / "data_backfill_v6"
    result = module.dry_run("all", output, tmp_path / "source", "20260731")

    assert result["network"] is False
    assert result["max_calls_per_minute"] == 60
    assert {item["name"] for item in result["phases"]} == {
        "stock_basic_trade_cal", "daily_1990_2004", "adj_factor", "daily_basic",
        "moneyflow", "margin_detail", "stk_limit", "stock_st", "financial", "index", "event",
    }
    assert not output.exists()


def test_output_root_rejects_v5_and_production_paths(tmp_path) -> None:
    allowed = tmp_path / "artifacts" / "data_backfill_v6"
    assert module.assert_staging_root(allowed / "experiment", tmp_path) == (allowed / "experiment").resolve()
    with pytest.raises(ValueError, match="output must stay"):
        module.assert_staging_root(tmp_path / "artifacts" / "alpha_phase1" / "tushare", tmp_path)


def test_seed_tasks_have_no_token_and_cover_full_calendar() -> None:
    tasks = module.seed_tasks("20260731")

    assert len(tasks) == 3
    assert {task.params.get("list_status") for task in tasks if task.dataset == "stock_basic"} == {"L", "D"}
    assert {task.dataset for task in tasks} == {"stock_basic", "trade_cal"}
    assert next(task for task in tasks if task.dataset == "trade_cal").params == {
        "exchange": "SSE", "start_date": "19901219", "end_date": "20260731",
    }
    assert "token" not in repr(tasks).lower()


def test_daily_history_clips_to_listing_lifecycle() -> None:
    stocks = pd.DataFrame({
        "ts_code": ["600001.SH", "300001.SZ"],
        "list_date": ["19910101", "20091030"],
        "delist_date": ["20030102", None],
        "list_status": ["D", "L"],
    })

    tasks = module.daily_history_tasks(stocks)

    assert len(tasks) == 1
    assert tasks[0].params["start_date"] == "19910101"
    assert tasks[0].params["end_date"] == "20030102"


def test_retired_t_prefixed_daily_code_uses_documented_query_alias() -> None:
    stocks = pd.DataFrame({
        "ts_code": ["T600018.SH"],
        "list_date": ["20000719"],
        "delist_date": ["20061020"],
        "list_status": ["D"],
    })
    task = module.daily_history_tasks(stocks)[0]
    assert task.key == "T600018_SH"
    assert task.params["ts_code"] == "600018.SH"
    assert task.params["_target_ts_code"] == "T600018.SH"


def test_financial_tasks_page_at_100_and_require_update_flag() -> None:
    stocks = pd.DataFrame({"ts_code": ["600001.SH"], "list_date": ["19910101"]})

    tasks = module.financial_tasks(stocks, "20260731")

    assert tasks
    assert all(task.page_limit == 100 for task in tasks)
    assert all("update_flag" in task.required_columns for task in tasks)


def test_gap_boundaries_do_not_refetch_existing_local_history(tmp_path) -> None:
    calendar = pd.Series(["20151231", "20160129", "20171229", "20180102"])
    tasks = module.index_tasks(calendar, "20260731")
    daily = [task for task in tasks if task.api_name == "index_daily"]
    weights = [task for task in tasks if task.api_name == "index_weight"]
    assert all(task.params["end_date"] == "20180101" for task in daily)
    assert all(task.params["end_date"] <= "20160128" for task in weights)
    assert module.HISTORICAL_GAP_ENDS["daily_basic"] == "20180701"


def test_event_tasks_only_request_missing_pledge_symbols(tmp_path) -> None:
    existing = tmp_path / "shards" / "pledge_detail"
    existing.mkdir(parents=True)
    (existing / "600001.SH.parquet").write_bytes(b"evidence")
    stocks = pd.DataFrame({
        "ts_code": ["600001.SH", "600002.SH"],
        "list_date": ["19910101", "19920101"],
    })
    tasks = module.event_tasks(stocks, "20260731", tmp_path)
    pledge = [task for task in tasks if task.api_name == "pledge_detail"]
    assert [task.params["ts_code"] for task in pledge] == ["600002.SH"]
    monthly = [task for task in tasks if task.api_name != "pledge_detail"]
    assert max(task.params["end_date"] for task in monthly) <= "20180701"


def test_fetch_task_pages_writes_identity_and_resumes_from_verified_cache(tmp_path) -> None:
    offsets: list[int] = []

    class Client:
        def query(self, api_name: str, **params: object) -> pd.DataFrame:
            offsets.append(int(params["offset"]))
            count = 2 if params["offset"] == 0 else 1
            return pd.DataFrame({
                "ts_code": [f"00000{number}.SZ" for number in range(count)],
                "ann_date": ["20001201"] * count,
                "proc": ["完成"] * count,
            })

    task = module.BackfillTask("repurchase", "200012", "repurchase", {"start_date": "20001201", "end_date": "20001231"}, ("ts_code", "ann_date", "proc"), page_limit=2)
    first = module.fetch_task(Client(), task, tmp_path, _Limiter(), 2)
    second = module.fetch_task(Client(), task, tmp_path, _Limiter(), 2)

    assert offsets == [0, 2]
    assert first["status"] == "fetched"
    assert second["status"] == "cached"
    assert first["rows"] == 2
    assert first["content_hash"] == second["content_hash"]
    assert list(tmp_path.rglob("*.parquet.request.json"))
    assert not list(tmp_path.rglob("*.tmp"))


def test_empty_source_is_incomplete_and_never_written(tmp_path) -> None:
    class Client:
        def query(self, api_name: str, **params: object) -> pd.DataFrame:
            return pd.DataFrame(columns=["ts_code", "trade_date"])

    task = module.BackfillTask("daily_1990_2004", "600001_SH", "daily", {"ts_code": "600001.SH", "start_date": "19910101", "end_date": "20041231"}, ("ts_code", "trade_date"))
    result = module.fetch_task(Client(), task, tmp_path, _Limiter(), 1)

    assert result["status"] == "source_empty"
    assert not list(tmp_path.rglob("*.parquet"))
    assert not list(tmp_path.rglob("*.request.json"))


def test_transient_empty_source_is_retried_before_success(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(module.time, "sleep", lambda _: None)

    class Client:
        calls = 0

        def query(self, api_name: str, **params: object) -> pd.DataFrame:
            self.calls += 1
            if self.calls == 1:
                return pd.DataFrame(columns=["ts_code", "trade_date"])
            return pd.DataFrame({
                "ts_code": ["600001.SH"], "trade_date": ["19910102"],
                "vol": [10.0], "amount": [100.0],
            })

    client = Client()
    task = module.BackfillTask("daily_1990_2004", "600001_SH", "daily", {"ts_code": "600001.SH"}, ("ts_code", "trade_date"))
    result = module.fetch_task(client, task, tmp_path, _Limiter(), 3)

    assert result["status"] == "fetched"
    assert result["attempts"] == 2
    assert client.calls == 2


def test_daily_contract_rejects_wrong_symbol_dates_and_duplicate_keys() -> None:
    task = module.BackfillTask(
        "daily_1990_2004",
        "600001_SH",
        "daily",
        {"ts_code": "600001.SH", "start_date": "19910101", "end_date": "20041231"},
        ("ts_code", "trade_date", "open", "high", "low", "close"),
    )
    good = pd.DataFrame({
        "ts_code": ["600001.SH"], "trade_date": ["19910102"],
        "open": [1.0], "high": [1.1], "low": [0.9], "close": [1.0],
        "vol": [10.0], "amount": [100.0],
    })
    module._validate_frame_contract(good, task)
    with pytest.raises(ValueError, match="outside requested"):
        module._validate_frame_contract(good.assign(ts_code="600002.SH"), task)
    with pytest.raises(ValueError, match="outside request bounds"):
        module._validate_frame_contract(good.assign(trade_date="20050101"), task)
    with pytest.raises(ValueError, match="duplicate primary"):
        module._validate_frame_contract(pd.concat([good, good], ignore_index=True), task)


def test_empty_page_after_full_page_is_only_pagination_terminator(tmp_path) -> None:
    class Client:
        def query(self, api_name: str, **params: object) -> pd.DataFrame:
            if params["offset"] == 0:
                return pd.DataFrame({"ts_code": ["x", "x"], "trade_date": ["1", "2"]})
            return pd.DataFrame()

    task = module.BackfillTask("daily", "x", "daily", {"ts_code": "x"}, ("ts_code", "trade_date"), page_limit=2)
    result = module.fetch_task(Client(), task, tmp_path, _Limiter(), 1)

    assert result["status"] == "fetched"
    assert result["rows"] == 2


def test_empty_cache_is_rejected_even_with_matching_identity(tmp_path) -> None:
    task = module.BackfillTask("daily", "x", "daily", {"ts_code": "x"}, ("ts_code", "trade_date"))
    path = tmp_path / "shards" / "daily" / "x.parquet"
    frame = pd.DataFrame(columns=["ts_code", "trade_date"])
    module.write_parquet_atomic(frame, path)
    metadata = {
        "request": module.request_identity(task),
        "request_hash": module.request_hash(task),
        "content_hash": module._hash_file(path),
        "rows": 0,
        "schema": list(frame.columns),
        "date_bounds": module._date_bounds(frame),
    }
    module.write_json_atomic(metadata, module._sidecar_path(path))

    result = module.fetch_task(object(), task, tmp_path, _Limiter(), 1)

    assert result["status"] == "cache_invalid"
    assert "empty" in result["message"]


def test_changed_request_and_legacy_shard_are_not_reused_or_overwritten(tmp_path) -> None:
    class Client:
        calls = 0

        def query(self, api_name: str, **params: object) -> pd.DataFrame:
            self.calls += 1
            return pd.DataFrame({"ts_code": ["600001.SH"], "trade_date": ["19910102"]})

    client = Client()
    original = module.BackfillTask("daily", "600001_SH", "daily", {"ts_code": "600001.SH", "end_date": "20041231"}, ("ts_code", "trade_date"))
    assert module.fetch_task(client, original, tmp_path, _Limiter(), 1)["status"] == "fetched"
    path = tmp_path / "shards" / "daily" / "600001_SH.parquet"
    before = module._hash_file(path)
    changed = module.BackfillTask("daily", "600001_SH", "daily", {"ts_code": "600001.SH", "end_date": "20051231"}, ("ts_code", "trade_date"))
    result = module.fetch_task(client, changed, tmp_path, _Limiter(), 1)

    assert result["status"] == "cache_invalid"
    assert client.calls == 1
    assert module._hash_file(path) == before

    module._sidecar_path(path).unlink()
    legacy = module.fetch_task(client, original, tmp_path, _Limiter(), 1)
    assert legacy["status"] == "cache_invalid"
    assert "legacy" in legacy["message"]
    assert client.calls == 1


def test_permission_error_is_not_retried_or_written(tmp_path) -> None:
    class Client:
        calls = 0

        def query(self, api_name: str, **params: object) -> pd.DataFrame:
            self.calls += 1
            raise RuntimeError("没有接口权限")

    client = Client()
    task = module.BackfillTask("daily_basic", "19901219", "daily_basic", {"trade_date": "19901219"}, ("ts_code", "trade_date"))
    result = module.fetch_task(client, task, tmp_path, _Limiter(), 3)

    assert result["status"] == "error"
    assert client.calls == 1
    assert not list(tmp_path.rglob("*.parquet"))


def test_checkpoint_starts_running_updates_each_task_and_finishes_incomplete(tmp_path) -> None:
    class Client:
        def query(self, api_name: str, **params: object) -> pd.DataFrame:
            return pd.DataFrame(columns=["ts_code", "trade_date"])

    task = module.BackfillTask("daily", "x", "daily", {"ts_code": "x"}, ("ts_code", "trade_date"))
    checkpoint = module._checkpoint_payload("daily_1990_2004", "20260731", [task], tmp_path, {"files": [], "source_hash": "abc"}, 60, 1, 1)
    path = tmp_path / "checkpoints" / "run.json"

    results = module.run_tasks([task], tmp_path, "unused", 60, 1, 1, checkpoint=checkpoint, checkpoint_path=path, client=Client())
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert results[0]["status"] == "source_empty"
    assert saved["state"] == "INCOMPLETE"
    assert saved["end_date"] == "20260731"
    assert saved["source"]["source_hash"] == "abc"
    assert saved["workers"] == 1
    assert saved["counts"] == {"source_empty": 1}
    assert saved["results"][0]["request_hash"]


def test_run_tasks_passes_explicit_sdk_timeout(monkeypatch, tmp_path) -> None:
    observed = {}

    class Client:
        pass

    def pro_api(token, timeout):
        observed.update(token=token, timeout=timeout)
        return Client()

    monkeypatch.setattr(module.ts, "pro_api", pro_api)
    checkpoint = module._checkpoint_payload(
        "adj_factor",
        "20260731",
        [],
        tmp_path,
        {"files": [], "source_hash": "abc"},
        60,
        1,
        3,
        15,
    )
    path = tmp_path / "checkpoint.json"
    module.run_tasks(
        [],
        tmp_path,
        "secret",
        60,
        1,
        3,
        checkpoint=checkpoint,
        checkpoint_path=path,
        request_timeout=15,
    )
    assert observed == {"token": "secret", "timeout": 15}
    assert checkpoint["request_timeout_seconds"] == 15


def test_run_tasks_batches_success_checkpoint_writes(monkeypatch, tmp_path) -> None:
    tasks = [
        module.BackfillTask("adj_factor", str(index), "adj_factor", {"trade_date": str(index)}, ("ts_code", "trade_date", "adj_factor"))
        for index in range(26)
    ]
    checkpoint = module._checkpoint_payload("adj_factor", "20260731", tasks, tmp_path, {"files": [], "source_hash": "abc"}, 60, 1, 1)
    writes = []

    monkeypatch.setattr(
        module,
        "fetch_task",
        lambda client, task, output_dir, limiter, max_attempts: {"task": {}, "status": "cached"},
    )
    monkeypatch.setattr(
        module,
        "write_json_atomic",
        lambda payload, path: writes.append((len(payload["results"]), payload["state"])),
    )

    module.run_tasks(tasks, tmp_path, "unused", 60, 1, 1, checkpoint=checkpoint, checkpoint_path=tmp_path / "checkpoint.json", client=object())

    assert writes == [(0, "RUNNING"), (25, "RUNNING"), (26, "COMPLETED")]


def test_cross_process_lock_is_exclusive_and_released_on_error(tmp_path) -> None:
    with module.staging_lock(tmp_path, "daily"):
        lock = tmp_path / module.DEFAULT_OUTPUT / ".backfill.lock"
        assert lock.exists()
        with pytest.raises(RuntimeError, match="another V6 backfill"):
            with module.staging_lock(tmp_path, "financial"):
                pass
    assert not lock.exists()

    with pytest.raises(RuntimeError, match="boom"):
        with module.staging_lock(tmp_path, "daily"):
            raise RuntimeError("boom")
    assert not lock.exists()


@pytest.mark.parametrize("value", ["20261301", "2026-07-31", "19891231", "abc"])
def test_end_date_validation_rejects_invalid_values(value) -> None:
    with pytest.raises(Exception):
        module.validate_end_date(value)


def test_status_reports_legacy_shards_lock_and_is_read_only_when_missing(tmp_path) -> None:
    output = tmp_path / "artifacts" / "data_backfill_v6"
    before = module.status(output, tmp_path)
    assert before["datasets"] == []
    assert before["checkpoint_states"] == {}
    assert not output.exists()

    path = output / "shards" / "daily" / "legacy.parquet"
    module.write_parquet_atomic(pd.DataFrame({"x": [1]}), path)
    lock = output / ".backfill.lock"
    module.write_json_atomic({"pid": 123}, lock)
    after = module.status(output, tmp_path)

    assert after["legacy_shards"] == 1
    assert after["lock"]["active"] is True
    assert after["safe_to_resume"] is False
