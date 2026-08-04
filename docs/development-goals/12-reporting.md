你是执行者，本文是 reporting 模块唯一任务来源；换会话先读 `development/12-reporting/PROGRESS.md`。目标是从版本化账户、信号、回测、风险、策略和数据质量事实生成可追溯报告快照；报告只拥有定义、派生指标、归因、质量和 artifact，不拥有/回写订单、成交、持仓、风险或上游指标。冲突按“源快照/对账 > 数据模式隔离 > 指标口径 > 质量 > 可复现 > 展示”处理。

## 冻结口径

- ReportDefinition 冻结类型(LIVE/PAPER/BACKTEST/RESEARCH)、受众、metric/template/code 版本、必需 source types、基准、无风险率、年化天数、FX/费用口径、敏感级别。修改新增版本。
- ReportInputSnapshot 每项含 source_type/source_id/as_of/content_hash/quality/source_mode/reference/facts；同一报告所有输入先冻结。LIVE 实际绩效只能使用 execution_ledger 成交/现金/估值且 reconciled；建议不计收益。BACKTEST/PAPER/LIVE 不能拼接成无标签曲线。
- BuildReport 幂等键=definition+period+所有输入 ID/hash+template/code。源修订产生新 run，旧 run/artifact 不覆盖。并发同键只保留一个。
- 指标计算一次形成 ReportMetric，保存 name/value/unit/definition/formula/source refs/drilldown；表格、图表和 HTML/CSV 只消费这些行，模板禁止重算。非有限数直接 quality FAIL。
- 手算指标至少 total return、max drawdown、turnover、fees、FX converted value；benchmark/risk-free/annualization/FX snapshot 随 run 保存。ExplainMetric 必须返回公式、快照和明细引用。
- Attribution 必含 ETF_TIMING、EQUITY_DAILY_SELECTION、CROSS_CONSTRAINT、CASH 四项的 return/risk/turnover/cost；两独立策略先留 run_id，最终贡献必须对账到组合值，禁止相加单策略独立回测收益冒充组合收益。
- 策略运营：个股 SELECT/KEEP/EXIT 数、候选稳定性/换手；ETF daily gate、实际 rebalance day、cash state。证券下钻用 instrument_id，展示名称/代码带 display_as_of。
- Quality 覆盖输入冻结/完整、日期、单位、引用、finite、artifact hash、敏感字段、账户 cash+position 与源 snapshot、归因合计。差 1 元即 FAIL；unreconciled/quality fail/交易日缺失为 INCOMPLETE，不可发布。
- Run 状态 CREATED→BUILDING→COMPLETED|INCOMPLETE|FAILED；仅全项 PASS 的 artifact `publishable=true` 并发出 ReportSnapshotBuilt，否则 ReportBuildFailed/Incomplete。

## 地界与任务 0

- 只允许改 `src/quant_trading_system/reporting/**`、`migrations/012_reporting.sql`、`tests/reporting/**`、本文、`development/12-reporting/**`。
- 01–11、MvpSelect、模块规格、pyproject 只读；禁止联网/装依赖/修改上游/输出真实敏感账号。
- 开工：上游 `1075 passed`、96 源码文件；12 规范 SHA256 `55A74E31403DBC633BA2D43A8FF41A14521DCADDD27424015EC66F44A3FE5AD4`，完成复核。
- MvpSelect 报告存在嵌套/扁平指标契约并行、模板自行取默认值/异常回退；禁止迁移，只参考展示字段名。

## 任务 1：定义、指标与模式隔离

- 实现 definition/input/run/metric/curve/trade/attribution/strategy-summary/artifact/quality/event；字段带 source reference 与时点。
- 实现 LIVE/PAPER/BACKTEST 输入适配契约和严格隔离；收益只由相应模式的已发生成交/现金/NAV 计算。用 Decimal 手算 total return、drawdown、turnover、fee、显式 FX。
- 同一 canonical result model 同时生成 summary/table/chart series；ExplainMetric 与来源断链检测。

## 任务 2：归因、质量与 artifact

- 双策略与 CROSS_CONSTRAINT/CASH 四项逐指标归因、组合 reconciliation；ETF/个股运营摘要齐全。失败只产不可发布 INCOMPLETE，不能用旧值/默认零伪装成功。
- 生成确定性 HTML/CSV manifest（内容/哈希/生成时点/敏感级别/引用）；escape 文本、脱敏账号、限制敏感明细下载。验证 artifact hash。
- GetReport/GetSleeveAttribution/ExplainMetric；相同输入返回同 run/hash，源 revision 新 run。

## 任务 3：存储与验收

- 内存/SQLAlchemy 双仓储与 `012_reporting.sql` 覆盖 definition/run/input binding/metric/attribution/strategy summary/artifact/quality/event，含唯一键、版本、外键、状态和事务约束。
- `tests/reporting` ≥120 passed、0 skipped；上游 1075 仍绿；compileall、mypy 十二模块、文档校验均 0。
- 正向覆盖手算收益/回撤/换手/费用/FX、差 1 元、unreconciled、缺交易日、nonfinite、引用断链、模式隔离、双策略归因、策略摘要、表图同源、幂等/修订、脱敏、hash 篡改和 SQLite。
- 反向验证临时允许 unreconciled 报告 publishable 或让图表重算指标，既有测试必须非 0；恢复后全绿。

## 纪律与完成条件

- 禁止模板计算业务指标、未成交建议计收益、混合模式曲线、两回测收益相加、覆盖旧报告、未对账正式化、吞异常/默认零、泄露账户号、删改/skip/todo 测试、白名单外修改或 `|| true`。测试只增不减。
- PostgreSQL live 缺口如实写 BLOCKED；每任务更新 PROGRESS。全量验收最多 3 轮，首轮全绿即停并贴证据。
