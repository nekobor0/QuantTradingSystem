# QuantTradingSystem 项目轮次日志

> 状态：持续维护（append-only）
> 初次整理：2026-08-24（Asia/Shanghai）
> 用途：为后续 agent 提供从项目建立至今的单一时间索引。详细证据仍以 Git、各阶段 `PROGRESS/BLOCKED/RESULTS`、数据 manifest 和审计文件为准。

## 维护规则

1. 每个形成可复用代码、数据资产、策略结论或运维状态变化的工作单元记为一轮；同一目标的连续小修可合并。
2. 已写入的轮次不覆盖、不改写结论；后续纠错新增一条 `UPDATE` 或 `ROLLBACK` 记录，并反向链接原轮次。
3. 每轮至少记录：日期、轮次号、任务、主要变更、数据与策略影响、Git 状态、证据索引、遗留事项。
4. Git 只保存代码、配置、迁移、测试和人工撰写的文档；行情、财务、事件、账户、日志、数据库、缓存、模型和生成工件只在本地数据层保存，不进入 Git。
5. 数据只有在具备来源与窗口、粒度/主键、覆盖与重复检查、PIT/可得时间、manifest/哈希及审计结论后，才记为“已落盘”；下载缓存或临时测试目录不算正式资产。

## 轮次索引

| 日期 | 轮次 | 当轮任务 | 主要开发、数据与策略工作 | Git 同步、更新或回滚 | 关键索引 |
|---|---:|---|---|---|---|
| 2026-07-28—2026-08-04 | R000 | 建立系统骨架与安全基线 | 建成证券主数据、行情、基本面、证券池、特征、策略、组合、信号、执行账本、回测、风控、报告、API/UI、平台运维 14 个模块；形成 PostgreSQL/TimescaleDB 目标架构和 TDX 历史桥。 | `4bb5bb2` 初始化安全仓库并同步 `main`；市场数据与生成工件排除在 Git 外。无源码回滚记录。 | `README.md`；`PROGRESS.md`；`docs/modules/README.md`；`docs/GITHUB_BACKUP_HANDOFF.md` |
| 2026-07-29—2026-08-05 | R001 | Alpha Phase 1 补充数据与因子筛选 | 完成价格量、股本供给、PIT 年报、资金流、股东户数、估值与基本面变化等多轮筛选；V6—V7 复盘后，价值与动量趋势过滤在 2018-07—2026-06 窗口形成历史候选，相关性较低；结论未自动晋级生产。 | 当时研究工件仅本地落盘；后续源码/治理材料混合存在于当前工作树，尚未形成完整远端闭包。无源码回滚记录。 | `development/16-alpha-factor-phase1/archive/pre_v7/CHECKPOINT_ROUND2_2026-07-29.md`；`development/16-alpha-factor-phase1/PROGRESS_V7.md`；`research_review/RESULTS.md` |
| 2026-08-06—2026-08-13 | R002 | 建立研究治理与策略层演进框架 | 建立 Research Program/Epoch、假设预算、证据等级、PIT/holdout 与注册治理；推进 V8—V12、冷/热层、注册表和调度设计；失败与阻塞结论保留，不以清缓存或换指标覆盖。 | 主要文档、研究代码和测试仍有大量未跟踪内容；不能视为已完成远端备份。 | `development/17-strategy-layer/QUANT_RESEARCH_NEXT_STAGE_GUIDE.md`；`development/17-strategy-layer/QUANT_TRADING_SYSTEM_PROGRESS_REVIEW_20260813.md`；`docs/Research Harness/` |
| 2026-08-14 | R003 | Git、CI、类型与项目交接基线 | 建立 GitHub Actions、依赖与 mypy 基线，补回被忽略的 `market_data` 模块；冻结无工件 checkout 时的测试行为；形成一次性项目状态总结。 | `7771c48` 及其前序提交已同步 `origin/codex/develop`；`docs/PROJECT_SUMMARY.md` 当前仍为未跟踪文件。无源码回滚记录。 | `docs/PROJECT_SUMMARY.md`；`.github/workflows/`；`pyproject.toml` |
| 2026-08-17—2026-08-19 | R004 | 纸面交易 P0/P1、红利税与 P2 影子框架 | 修复模拟仓执行与校验；研究红利税持有期/FIFO 约束；恢复 8 月 17—19 日纸面交易链；确认红利月频、波动日频，扫描保持日频；建设独立 P2 健康检查、快照对账和前端流程展示。 | `b3b55b9`、`16937fe` 已同步 `origin/codex/paper-p0-p1`；后续实现通过 `origin/codex/paper-tax-p2` 可达。无生产订单或源码回滚。 | `paper_trading/README.md`；`paper_trading/`；`d90241f` |
| 2026-08-19 | R005 | AB 双策略模拟仓与可视化 | A=75% 波动/25% 红利，B=25% 波动/75% 红利；统一 T 日扫描、T+1 执行；双策略净值、分仓、信号、结算、P2 健康与外部快照对账在同一前端展示。 | `08aafec` 已作为 `origin/codex/paper-tax-p2` 的祖先远端备份。 | `paper_trading/app_ab.py`；`paper_trading/templates/`；`08aafec` |
| 2026-08-19—2026-08-20 | R006 | 数据资产目录、新鲜度矩阵与统一 PIT 事件中心 | 建立数据资产目录、数据新鲜度/覆盖元数据和统一 PIT 事件 hub；扩充宏观、财务、回购、股东、限售解禁、跨资产等数据管线；正式数据位于本地 bronze/silver 与审计目录。 | `a43b5b7`、`8032f14` 仅在本地 `codex/data-catalog-pit`；截至 2026-08-24 因 GitHub 443 连接失败，尚未远端同步，不得删除对应隔离 worktree。 | `config/data_assets.json`；`artifacts/data_expansion/bronze/expansion_manifest.json`；`artifacts/data_expansion/silver/pit_events.manifest.json`；`artifacts/data_audits/` |
| 2026-08-21 | R007 | 更贴近实盘的 T+1 分阶段成交 | 对 2018-07-02—2026-08-19 官方涨停价覆盖区间，比较原开盘同时买卖与“卖出按开盘、排除涨停、买入按开收均价”的执行规则；模拟仓实现分阶段下一日执行。 | `0ad4c93`、`361cfd2` 已同步 `origin/codex/paper-tax-p2`。无生产订单。 | `paper_trading/EXECUTION_RULE_BACKTEST.md`；`paper_trading/execution.py`；`361cfd2` |
| 2026-08-21 | R008 | 独立 Alpha 数据补充与审计 | 聚焦 A2、B2、B3、B4 可得性；完成可取得方向的数据补充与研究。A2 可转债数据 739,218 行/991 只/1,976 日，B4 指数数据 65,499 行/31 指数/2,583 日，组合键无重复，审计 PASS；不可得方向挂起。 | 数据不进 Git；审计代码与安全白名单提交 `2ce5c54`、`62499e2`，并作为 `origin/codex/execution-lot-ledger-checkpoint` 的祖先获得远端备份。 | `artifacts/independent_alpha_20260821/DATA_AUDIT.json`；`62499e2` |
| 2026-08-21—2026-08-24 | R009 | 执行账本类型、安全与持仓批次闭包 | 修复 3 个 mypy 执行账本错误；隔离 `session.jsonl`；窄化测试/审计安全规则；加入 lot-aware 持仓、公司现金行动、持久化回填与恢复演练，共 24 个文件形成完整闭包。 | `9051cfc`、`2df5604` 已同步 `origin/codex/execution-lot-ledger-checkpoint`；远端与本地提交一致。全量测试 1678 通过/1 跳过，专项 452 通过。Git 同步隔离 worktree 已删除，无回滚。 | `migrations/015_execution_ledger_position_lots.sql`；`migrations/016_execution_ledger_corporate_cash_actions.sql`；`src/quant_trading_system/execution_ledger/`；`2df5604` |
| 2026-08-24 | R010 | 备份、落盘与临时产物审计 | 明确 Git 与数据落盘边界；删除已远端备份的执行账本 worktree、三个纸面交易 Git 同步暂存目录和探针；删除可再生的独立 Alpha pytest 落盘测试目录（491 文件，约 5.3 MB）；正式数据、manifest、审计文件与 quarantine 保留。 | 数据目录分支提交前检查通过：安全 0 风险、mypy 133 文件、pytest 1681 通过/1 跳过、交易安全专项 420 通过；两次推送均因 GitHub 443 不可达失败，因此 worktree 保留。 | 本文；`AGENTS.md`；`.gitignore`；`artifacts/independent_alpha_20260821/DATA_AUDIT.json` |
| 2026-08-25 | R011 | 中国宏观数据可得性、研究价值与落盘优先级评估 | 读取宏观方法论作为研究约束、YAML 作为 145 条 ingestion backlog；结合现有 8 个 Tushare 宏观 Bronze 资产、策略/因子注册表、模拟仓和研究结论，形成 P0 + W1/W2/W3/W4/HOLD 排序及 65—107 人日总体估算；未启动数据抓取、正式审计或宏观回测。 | 基线 `62499e2`，分支 `codex/inverse-signal-pool-v3`；工作树原已脏。本轮仅归档文档并更新索引；`git fetch --prune origin` 因连接被重置失败，未提交、未推送、未回滚。 | `development/18-macro-data-layer/R011_macro_data_prioritization/` |

## 当前 Git 备份快照（2026-08-24）

| 工作单元 | 本地提交 | 远端状态 | 处置 |
|---|---|---|---|
| 稳定主线 | `4bb5bb2` / `7771c48` | `origin/main`、`origin/codex/develop` 已同步 | 保留 |
| 纸面交易 P0/P1、税务/P2、AB 与分阶段执行 | 至 `361cfd2` | `origin/codex/paper-p0-p1`、`origin/codex/paper-tax-p2` 已同步 | 同步暂存目录已删除 |
| 安全白名单、独立 Alpha 审计、执行 lot 账本 | 至 `2df5604` | `origin/codex/execution-lot-ledger-checkpoint` 已同步 | 隔离 worktree 已删除；当前脏工作树副本不自动清理 |
| 数据目录、PIT 与扩充管线 | `8032f14` | 未同步；两次 GitHub 连接失败 | 保留 `temp/data-catalog-pit`，网络恢复后推送再删除 |
| 当前工作树其余研究/脚本/文档 | 混合修改与未跟踪文件 | 未形成可验证、可复测的完整远端闭包 | 先分类、冻结、复测；不得批量提交或删除 |

## 后续轮次模板

```markdown
### YYYY-MM-DD · RNNN · STATUS

- 任务：
- 主要开发或修改：
- 数据增删/落盘：
- 策略测试与结论：
- Git：分支、基线、最终提交、远端同步、更新/回滚；如未同步写明原因。
- 验证：安全扫描、compileall、mypy、pytest、数据审计。
- 索引：代码、迁移、文档、manifest、审计报告。
- 遗留/风险：
```

## R011 UPDATE · 2026-08-26 · P0 Shibor / PMI 正式回填与审计

- 任务：在 D1—D5 全部确认后，实现并执行 P0 schema、Shibor 和 PMI 正式官方源回填、不可变落盘、PIT 时间门禁及 Tushare 独立对账。
- 代码：新增可断点续跑的年度/页面分片、PMI 目录发现、三代页面解析、curated 合并、对账与 quarantine；统一 schema 增加 `tradable_at`。
- 数据：Shibor 2006-10-08—2026-08-25，4,966 日 × 8 期限 = 39,728 条；PMI 204 个页面 vintage、13,530 条，覆盖 2009-05—2026-07，已知缺口 2010-04。正式数据位于 Git 忽略的 `artifacts/macro_r011/`。
- 审计：PMI 2016-01—2026-07 与 Tushare 762/762 单元格精确一致；Shibor 21,040 个重叠单元格中 42 个差异，全部诊断为 Tushare 2022-04-18—2022-05-17 的 O/N 与 3M 精确列互换。原 Bronze 未修改。
- Readiness：PMI 全表因 2010-04 缺月保持关闭，2016-01—2026-07 获批为首个研究窗口；Shibor 数值层通过，但历史非同期采集，必须执行 `tradable_at`，历史 PIT 回测门禁关闭。
- Git：隔离分支 `codex/r011-macro-samples`；确认检查点 `0b4fd0a` 已由用户手动推送；正式实现本地检查点 `a7e854e`。最终提交和远端状态以本轮完成交接为准。
- 验证：工作树安全扫描 0 风险；R011 聚焦测试、compileall、项目 mypy（按既有策略排除 research）和交易安全专项已在实现检查点通过；最终全量测试结果见完成交接。
- 索引：`development/18-macro-data-layer/R011_macro_data_prioritization/05_P0_SHIBOR_PMI_BACKFILL_AUDIT.md`；`config/macro_sample_registry.json`；`scripts/data_lake/run_macro_samples.py`；`src/quant_trading_system/research/macro_data/`。
- 遗留：2010-04 PMI 官方缺口；国家数据端点 403；Shibor forward latency evidence；Tushare Shibor Bronze 列互换根因与派生修复层。

## R011 UPDATE · 2026-08-26 · F1—F3 修复与时点决策

- F1：全重叠区跨列检测确认仅 21 日、42 单元格发生 O/N 与 3M 精确互换；以 CFETS 官方值修复 Bronze 总表和 2022 分片，原件与前后 SHA-256 保存在本地 repair manifest。修复后 Shibor 21,040/21,040、PMI 762/762 精确一致。
- F2：CFLP 官方存档确认 `2010-04 HEADLINE=55.7`、发布页时间 2010-05-01 09:06；五个构成指数仍需从国家数据 `A0B01` 人工原生导出，禁止插值或从 headline 反推。
- F3：最近六个月数值完整但历史接口无逐日实际发布时间。用户批准历史规则：策略交易日 D 只使用 `reference_period < D` 的最新 Shibor；D1 同日规则仅用于 forward observation。
- 代码：新增 `repair.py`、修复 CLI 和拒绝非精确异常集合的测试；对账通过后限制文本仅保留 historical capture timing。
- 索引：`development/18-macro-data-layer/R011_macro_data_prioritization/06_F1_F2_F3_REMEDIATION_DECISION.md`；本地 `artifacts/data_expansion/repairs/r011_shibor_on_3m_swap/repair_manifest.json`。
- 遗留：用户人工导出 2010-04 PMI 六字段；积累至少六个月 Shibor forward 首次成功采集日志后复审同日 11:05 PIT 规则。
