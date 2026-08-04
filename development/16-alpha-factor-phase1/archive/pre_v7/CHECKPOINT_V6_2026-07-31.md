# V6 Checkpoint — 2026-07-31

## 当前结论

- `GOAL_V6.md`保持只读，SHA256：`4030CA236BDC3931A380D6C8C91577827C9087326C4E666C19AB97136B68F48F`。
- Leader任务书：`V6_LEADER_BRIEF.md`。
- V6 Phase 1五项基础设施完成，V5三个基线漂移检查PASS。
- 首轮唯一防御机制`downside_beta_v6`按事前登记和复审后股票池口径重算完成，数据审计PASS，但固定验证经济门槛失败，结论`REJECTED`，未进入实时影子。
- Tushare历史审计PASS。隔离回填已完成股票清单/交易日历及1990—2004日线；`adj_factor`正在断点续跑。

## 主线证据

- 注册：`artifacts/registrations/downside_beta_v6.md`
- 信号：`artifacts/evaluations/downside_beta_v6_signals.parquet`
- 数据审计：`artifacts/data_audits/downside_beta_v6.json`
- 月度组合/持仓：`artifacts/evaluations/downside_beta_v6_{monthly,holdings}.parquet`
- 评价：`artifacts/evaluations/downside_beta_v6_evaluation.json`
- 多重检验：`artifacts/evaluations/multiple_testing_{ledger,summary}_v6.*`

固定验证期相对V5 24月滚动回归基线：

| 基准 | 下跌月平均主动收益 | Downside Beta变化 | 最大回撤变化 | 年化净超额变化 |
|---|---:|---:|---:|---:|
| 沪深300 | -0.085% | +0.011 | -0.27pp | -0.53pp |
| 中证1000 | -0.180% | +0.026 | -1.08pp | -1.79pp |

第63项试验：先按月份合并两个相关基准后，下跌月候选相对基线收益变化均值-0.142%，HAC t=-5.023，双侧p=0.00000051，区块bootstrap 95%区间[-0.201%,-0.086%]。BH-FDR显著但方向不利，不能晋级。

## Tushare支线证据

- 审计：`artifacts/data_audits/tushare_history_v6.{json,md}`
- 执行器：`scripts/v6/backfill_tushare_v6.py`
- staging：旧证据`artifacts/data_backfill_v6/shards/**`；修复后续跑`artifacts/data_backfill_v6/v2/**`
- 已完成：v2 `stock_basic_trade_cal` 3/3；`daily_1990_2004` 1,378/1,378，逐片审计PASS，2,182,795行，1990-12-19—2004-12-31。
- 当前阶段：v2 `adj_factor`全历史8,694个按交易日不可变分片。两次网络挂起均保留不可变缓存和原checkpoint；`19930330`空响应已在续跑中修复。
- 第三次续跑在5,932/8,694处再次网络挂起，并记录`20101206`一次可重试传输错误；超过5分钟无checkpoint后精确终止PID 17404并核验清理遗留锁，缓存和历史checkpoint保留。
- 第四次续跑：2026-08-01 03:16为6,238/8,694（71.75%；6,167 cached、71 fetched），PID 27984和锁正常；`20101206`已补齐、错误清零，manifest记录15秒SDK超时。
- 串行守护：`scripts/v6/run_tushare_backfill_sequence_v6.ps1`在`adj_factor`完成并审计后执行后续白名单；当前代码显式记录SDK请求超时，后续新阶段固定15秒。任何阶段两次仍不完整或审计失败即停。
- 后续顺序：`adj_factor` → `daily_basic` → `moneyflow` → `margin_detail` → `stk_limit` → `stock_st` → `financial` → `index` → `event`
- 禁止：覆盖V5 Tushare聚合、直接写生产库、将源空响应填零、未完成schema/PIT/lineage即发布。

## 验证

- V6 tests：50 passed。
- 旧alpha_phase1回归：57 passed。
- 全仓：1612 passed。
- V5三基线漂移检查：PASS。

## 续跑命令

```powershell
$env:PYTHONPATH='src'
python -m scripts.v6.backfill_tushare_v6 --status --output-dir artifacts/data_backfill_v6/v2
powershell -ExecutionPolicy Bypass -File scripts/v6/run_tushare_backfill_sequence_v6.ps1
```

该阶段可重复执行，已存在且校验通过的分片会标记`cached`。

## 2026-08-01 04:07 增量检查

- `adj_factor`：7,816/8,694（89.90%），6,167 cached、1,649 fetched、0 empty/error。
- 活跃 owner：PID 27984；checkpoint=`artifacts/data_backfill_v6/v2/checkpoints/adj_factor_20260731T190428011364Z.json`；显式SDK timeout=15秒。
- 进程、锁和checkpoint均健康，继续由cell 294内的串行guardian守护；不得并行启动第二个Tushare抓取器。
- 后续事件：第五次网络/SDK长挂发生在8,442/8,694（97.10%）；超过5分钟无更新后已精确停止PID 27984并核验清理其遗留锁，成功分片与checkpoint完整保留。下一次运行应全部命中8,442个缓存，仅抓剩余252项。
- 当前恢复点（04:58）：cell 392 / owner PID 18160 / checkpoint `adj_factor_20260731T205643664641Z.json`，2,144/8,694 cached；该cell的shell timeout为1小时，继续等待其跨过8,442旧断点。
- 05:05修复checkpoint逐项全量写盘造成的O(n²) I/O，改为每25项/异常/终态写盘；测试backfill 25 passed、V6 50 passed。
- `adj_factor`最终审计PASS：8,694 valid、18,879,553行、1990-12-19—2026-07-31、staging only。
- 当前阶段：`daily_basic`，cell 417；联网提权后checkpoint `daily_basic_20260731T211220356402Z.json`于05:13为50/6,732 fetched、0 error。
- 当前长期执行点：24小时联网cell 426，`daily_basic_20260731T211607750201Z.json`于05:17为175/6,732（126 cached、49 fetched、0 error），owner PID 39048。
- 05:33更新：同一checkpoint为700/6,732（10.40%；126 cached、574 fetched、0 error），最新交易日1993-09-15。
- 05:54更新：同一checkpoint为1,400/6,732（20.80%；126 cached、1,274 fetched、0 error），最新交易日1996-07-03。
- 06:16更新：同一checkpoint为2,100/6,732（31.19%；126 cached、1,974 fetched、0 error），最新交易日1999-05-20。
- 06:38更新：同一checkpoint为2,800/6,732（41.59%；126 cached、2,674 fetched、0 error），最新交易日2002-04-22。
- 06:57更新：同一checkpoint为3,400/6,732（50.51%；126 cached、3,274 fetched、0 error），最新交易日2004-10-18。
- 07:18更新：同一checkpoint为4,050/6,732（60.16%；126 cached、3,924 fetched、0 error），最新交易日2007-06-25。
- 07:40更新：同一checkpoint为4,725/6,732（70.19%；126 cached、4,599 fetched、0 error），最新交易日2010-03-29。
- 07:52晨间核验：同一checkpoint为5,075/6,732（75.39%；126 cached、4,949 fetched、0 error），最新交易日2011-09-01；owner PID 39048，D盘剩余303.8GB。
- 08:03更新：同一checkpoint为5,400/6,732（80.21%；126 cached、5,274 fetched、0 error），最新交易日2013-01-07。
- 08:26更新：同一checkpoint为6,075/6,732（90.24%；126 cached、5,949 fetched、0 error），最新交易日2015-10-22。
- `daily_basic`最终审计PASS：6,732 valid、8,842,324行、1990-12-19—2018-06-29、staging only。
- 当前阶段`moneyflow`：checkpoint `moneyflow_20260801T005250648234Z.json`于08:54为50/2,020 fetched、0 error；唯一owner PID 29272，父guardian PID 30808。
- `moneyflow`最终审计PASS：2,020 valid、4,841,995行、2010-01-05—2018-04-27、staging only。
- 当前阶段`margin_detail`：checkpoint `margin_detail_20260801T020652430547Z.json`于10:08为50/2,006 fetched、0 error；owner PID 8532。
- `margin_detail`最终审计PASS：2,006 valid、1,214,919行、2010-03-31—2018-06-29、staging only。
- 当前阶段`stk_limit`：checkpoint `stk_limit_20260801T031210034429Z.json`于11:13为50/2,795 fetched、0 error；owner PID 28560。
- `stk_limit`最终下载2,795/2,795并独立审计PASS：2,795 valid、6,484,477行、2007-01-04—2018-06-29、request-set hash=`802e17b3314d0b7578be60a9948fc298b06297735bd833f31d629868b93aaf40`、未发布生产库。
- 当前阶段`stock_st`：checkpoint=`stock_st_20260801T044554149748Z.json`，owner PID 28700。最初请求出现`source_empty`；按既定约束空响应不写parquet、不计成功，最终必须由完整任务集审计决定PASS或DATA_BLOCKED。
- `stock_st`最终审计为`DATA_BLOCKED`而非PASS：607任务中453 valid、154 missing，32,889行，实际范围2016-08-09—2018-06-29，request-set hash=`a6aef9499a4666cd01450ce69a5e124136b622047a07f3085e1fd65a22876644`。两轮复验均确认固定源空洞，瞬时网络错误已补齐；禁止填零或发布。
- guardian新增`-StartPhase`参数用于从独立后续阶段恢复。当前从`financial`续跑：checkpoint=`financial_20260801T053832415250Z.json`，13:40为43/6,555（42 fetched、1 source_empty），owner PID 38528；后续仍按`financial → index → event`串行执行并逐阶段审计。
