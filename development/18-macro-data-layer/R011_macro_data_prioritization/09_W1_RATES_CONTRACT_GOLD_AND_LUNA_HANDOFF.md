# R011 W1 利率样板：契约、两期 Gold 与 Luna Handoff

状态：`W1_D1—W1_D9 CONFIRMED / GOLD READY / ONE-MONTH SHADOW ONLY`

## 已冻结资产

- 契约：`config/macro_w1_rates_contract.json`
- 契约及 gold 校验器：`scripts/data_lake/validate_macro_w1_rates_contract.py`
- 两期本地 gold：`artifacts/macro_r011/gold_fixtures/w1_rates/{2026-08-24,2026-08-25}`
- W1 注册表：`config/macro_w1_confirmation_registry.json`

Gold 含中国货币网 `wghtdAvgRepoRate` 字段的 DR007/R007、人民银行 7 天逆回购公告，以及 2026-08-25 MLF 多重价位招标的结构性缺失证据。真实小样属于市场数据，按项目政策只保存在被忽略的 `artifacts/`，不得提交；契约、校验器和测试可提交。

关键断点：人民银行自 2025 年 3 月起将 MLF 改为固定数量、利率招标、多重价位中标，已无统一中标利率。因此 `CN.PBOC.MLF.1Y.RATE` 在 2025-03-01 后必须零输出，并写结构性缺失审计；不得使用操作金额、媒体估算或旧值延续替代。

## 交给 GPT-5.6 Luna 的任务书

```text
你是 QuantTradingSystem 的执行型数据工程 Agent，在 D:\Claude_work_Territory\QuantTradingSystem\temp\r011-macro-samples 工作。
唯一目标是按已冻结契约完成 DR007/R007 + OMO/MLF 的解析器、2026-07-27—2026-08-25 一个月 shadow 回填和初步审计，不做全历史推广或策略接入。
最难点是区分 R/DR 加权利率与 FR/FDR 定盘利率，并正确处理 2025-03 后 MLF 已无统一利率的制度断点。
输出必须包括可复跑代码、本地被忽略的 raw/normalized/audit、专项测试，以及清晰的 PROGRESS.md；源不可得时输出 BLOCKED.md 证据包。
不要向用户提问；在下列边界内自行探测、修复和验证，达到完成条件或止损条件后停下。

## 我替领导拍的板
- W1_D1—W1_D9 已全部确认，不再重开口径讨论。
- 官方来源优先；Tushare 只能独立对照，绝不能补官方缺口或覆盖官方值。
- DR007/R007 只取中国货币网字段 `wghtdAvgRepoRate`；不得取 FR007/FDR007、收盘利率或“利率债加权平均”字段。
- 历史 DR/R 按 W1_D5：下一策略交易日 09:30 才可见；事件序列保持 sparse，不前填。
- 2025-03-01 后不得生成 `CN.PBOC.MLF.1Y.RATE`，只记录 `UNIFIED_RATE_STRUCTURALLY_UNDEFINED`。

## 界限
可改：`src/quant_trading_system/research/macro_data/{adapters.py,pipeline.py,backfill.py}`、新增 `scripts/data_lake/run_macro_w1_rates_shadow.py`、相关 `tests/research/test_macro_w1_rates*.py`、本轮说明文档。
只读：`config/macro_w1_rates_contract.json`、`config/macro_w1_confirmation_registry.json`、两期 gold 全部文件、既有 Shibor/PMI 资产。
运行产物只写 `artifacts/macro_r011/{raw,normalized,curated,audits,state,quarantine}`；市场数据、HTML、JSON、CSV、Parquet 不得 git add/commit。
禁止触碰策略、交易、风险、账户代码；保持 `TRADING_MODE=paper`、`ALLOW_LIVE_TRADING=false`、`ENABLE_ORDER_SUBMISSION=false`。

## 现状与任务0
先运行并把结果写入 `artifacts/macro_r011/state/w1_rates_luna/PROGRESS.md`：
`git status --short --branch`
`python scripts/data_lake/validate_macro_w1_rates_contract.py`
`python scripts/data_lake/validate_macro_w1_gate.py`
`python -m pytest -q tests/research/test_macro_w1_rates_contract.py tests/research/test_macro_w1_confirmation_gate.py`
基线应为全部通过。先完整阅读 Constitution、W1 gate、契约、校验器和两期 expected；不得修改 gold 来迁就代码。

## 任务1：解析器先过 Gold
实现两个确定性解析入口：CFETS repo JSON→DR007/R007；PBOC release HTML→OMO 7D/MLF regime audit。对两期 raw 逐字节 SHA 校验，输出必须与 expected 的行、值、时间、source_record_id、raw_sha256 完全一致。测试必须离线，不访问网络。

## 任务2：一个月 Shadow 获取
使用契约中的官方 URL、方法、表单字段，按日期获取 2026-07-27—2026-08-25。每次响应先不可变落 raw+manifest，再解析；`data.lastDate` 不等于请求日、空 records、验证码/HTML 伪响应、非 200 均隔离。PBOC 从官方索引发现公告页并保存页面时间。不要把 fixture 值硬编码进生产输出。

## 任务3：审计与交付
生成 `artifacts/macro_r011/audits/w1_rates_shadow.json`，至少报告：请求/成功/空响应日期、DR/R 同日覆盖率、重复键、值域、日变、R007-DR007 差、事件发现/解析率、时间顺序、raw hash、MLF 结构性缺失、隔离清单。另写一页 Markdown 总结来源可得性与是否可扩大回填。

## 规矩
- 先 fixture 后联网；每个修复补回归测试。
- 禁止前填、插值、用旧 MLF 利率延续、用操作量冒充利率、用第三方填官方缺失。
- 反向验证：临时篡改一个 gold 值、互换两个 indexType、注入一条 2026 MLF rate，校验器都必须失败；测试后恢复临时副本。
- 官方历史路径连续 3 种独立尝试仍不可达即止损：保留 URL、参数、响应码/摘要到 `BLOCKED.md`，完成可得区间但标记 `research_ready=false`，不得降级来源绕过。
- 保持 `PROGRESS.md`：已做、证据、下一步；失败不静默跳过。

## 完成条件
1. 两期 gold 精确通过，专项测试全绿，且反向验证三项均能抓错。
2. 一个月范围所有日期都有“官方行或可解释状态”，无 unexplained missing；DR/R 同日覆盖率≥95%，重复键=0，OMO 官方事件解析率=100%，2025-03 后 MLF rate 行=0。
3. `python scripts/git_safety_check.py --worktree`、`python -m compileall -q src scripts`、聚焦 research 测试通过；基线失败须单列，不归因于本轮。
4. 只提交代码、测试、说明；所有市场数据仍为 ignored。最后报告分支、baseline/final commit、检查结果、未解决风险，不 push，等 Sol 复核。
5. 若官方端点无法满足一个月，只有在完成止损证据包、可得区间审计和 `research_ready=false` 后才可停止，并明确标记 BLOCKED，不能声称完成。
```
