# TdxQuant 历史日线桥接

## 定位

`tdx_bridge` 是市场数据模块的 Windows 边缘适配器。它只处理历史日线回补和显式交易日的每日增量，不订阅实时行情、不调用交易接口，也不持有新的行情事实表。

数据路径：通达信量化终端 → 本机 HTTP `127.0.0.1:17709` → 不可变原始 JSON → `RawBarInput` → 现有 `MarketDataService` 质量门禁 → `dataset_batches` / `market_bars`。

## 前提

- Windows 上运行并登录支持 TQ 的通达信终端。
- 终端目录包含 `PYPlugins/user/tqcenter.py`、`TPyth.dll`、`TPythClient.dll`，17709 正在监听。
- 已在客户端“盘后数据下载”中下载所需日线；空返回被当作失败。
- `QTS_DATABASE_URL` 指向已经执行迁移 001、002 的数据库；脚本不建表、不迁移。
- 单证券 `backfill` 仍要求已有 `source=tdx` 别名；`bulk-backfill` 会根据通达信稳定基础字段补建缺失主数据，并把分类依据写入来源记录。

## PostgreSQL 回环连接

```powershell
docker compose -f deploy\compose.yaml -f deploy\compose.tdx.yaml up -d db
$env:QTS_DATABASE_URL = 'postgresql+psycopg://qts:<本机密钥>@127.0.0.1:5432/qts'
```

基础 Compose 不发布数据库；专用覆盖文件只绑定 `127.0.0.1`，供运行在 Windows 宿主机上的桥接器使用。

## 批量清单与全量回补

先从客户端导出当前“所有A股”和“ETF基金”清单：

```powershell
.\.venv\Scripts\python.exe scripts\tdx_bridge.py export-symbols `
  --markets 5 31 `
  --output artifacts\tdx_bridge\universe_a_etf.csv
```

清单也可以自行提供：纯文本每行一个代码，或 CSV 使用 `symbol,name,asset_type` 列。CSV 的 `asset_type` 可显式填写 `A_SHARE`、`ETF_DOMESTIC`、`ETF_OVERSEAS_LINKED`；自动导出的 ETF 使用 `ETF_AUTO`，按名称关键词做首轮国内/海外分类，报告后应人工复核。

```powershell
.\.venv\Scripts\python.exe scripts\tdx_bridge.py `
  --raw-dir artifacts\tdx_bridge\raw `
  --timeout-seconds 180 `
  bulk-backfill `
  --symbols-file artifacts\tdx_bridge\universe_a_etf.csv `
  --start 2005-01-01 `
  --end 2026-07-28 `
  --batch-size 4 `
  --max-retries 2 `
  --checkpoint artifacts\tdx_bridge\bulk_checkpoint.json `
  --report artifacts\tdx_bridge\bulk_report.json
```

每批成功后原子更新检查点；重跑同一命令会跳过已完成证券。批量失败达到重试上限后自动拆成单证券定位，不让一个空数据代码拖垮整批。最终报告包含请求/成功/失败证券数、覆盖比例、每个证券最早/最晚日期、不同交易日数、实际行数和失败原因。

## 历史回补

```powershell
$env:QTS_DATABASE_URL = '<从安全配置注入，不要写入仓库>'
python scripts\tdx_bridge.py backfill `
  --symbols 600000.SH `
  --start 2024-01-01 `
  --end 2024-01-31
```

脚本固定发送：`period=1d`、`count=-1`、`dividend_type=none`、`fill_data=false`。同一原始响应按 `(source, checksum)` 幂等；不同修订形成新批次和新 revision，不覆盖旧事实。

## 每日增量

调度器应在交易日收盘且盘后数据完成更新后传入明确日期：

```powershell
python scripts\tdx_bridge.py incremental `
  --symbols 600000.SH 510300.SH `
  --date 2026-07-28
```

首期不自动猜“上一交易日”，避免节假日、停牌或任务漏跑被静默吞掉。漏跑日期使用 `backfill` 补齐。

全市场盘后更新使用独立脚本。默认取中国标准时间当天；同一天重复执行会从日期独立检查点续跑，并由 `(source, checksum)` 保证已发布批次幂等：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_tdx_daily_update.ps1
```

补跑指定交易日或降低并行数：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_tdx_daily_update.ps1 `
  -TradingDate 2026-07-28 `
  -Workers 2
```

脚本在写库前检查日期不在未来、当天已过 15:30、非周末、Docker PostgreSQL 正在发布 5432、`TdxW.exe` 已运行且 `127.0.0.1:17709` 正在监听；随后刷新 A 股和 ETF 清单，以 20 只/批执行单日批量增量。检查点与报告写入 `artifacts/tdx_bridge/daily/YYYY-MM-DD/`。节假日仍应由外部交易日调度器跳过；若误运行，空返回会明确失败而不会发布空批次。

## 验证

```powershell
python scripts\tdx_bridge.py verify `
  --symbol 600000.SH `
  --start 2024-01-01 `
  --end 2024-01-31 `
  --expected 22
```

完成判据是 `distinct_dates=22` 且 `rows=22`。重复执行同一回补后再次验证，行数不得增加。

## 单位与时间

- OHLC：元，不复权。
- `Volume`：当前 TQ 返回值按股写入；扩展到其他市场前必须与第二来源抽样核对。若确认某客户端返回“手”，显式传顶层参数 `--volume-unit lots`，由现有交易规格换算成股。
- `Amount`：TQ 的万元转换为人民币元（乘 10000）。
- A股日线结束时间：交易日本地 15:00，入库为 UTC 07:00；`available_at` 是实际采集时间。
- 原始 `ForwardFactor` 保留在不可变 JSON 中。本功能尚不发布复权因子，不能声称已经生成稳定 HFQ 序列。

## 失败语义

网络不可达、TQ `ErrorId` 非零、任一证券空返回、字段长度不一致、区间外日期、证券别名缺失、质量门禁拒绝或数据库表缺失均失败。单批命令使用退出码 2；批量完成但仍有失败证券使用退出码 3，并保留报告和检查点。失败不会发布空批次；原始响应可能已按“raw first”原则保留，便于审计。
