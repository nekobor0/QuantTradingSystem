# R011 中国宏观数据获取与落盘优先级评估

> 日期：2026-08-25（Asia/Shanghai）
> 状态：`ASSESSMENT_ONLY / NO_ACQUISITION_STARTED`
> 决策对象：`02_china_macro_data_universe_v0.1.yaml` 的 145 条候选序列
> 本轮边界：只做现状盘点、官网可得性核验、研究价值判断和工时估算；未抓取、未补数、未做正式数据审计、未开展宏观因子或策略回测。

## 1. 结论先行

不建议按 YAML 的 `T1 -> T2 -> T3` 机械全量抓取。更合适的顺序是：

1. **先建 PIT 数据治理骨架**，再补任何新序列；
2. **W1 先完成 34 条“宏观状态脊柱”**：利率/流动性、PMI、价格、信用、增长锚；
3. **W2 再完成 26 条“传导与外部状态”**：需求、投资、地产、财政、外贸、跨境资金；
4. **W3 的 61 条结构分项/Nowcast 数据按边际贡献进入**，不得因为容易抓就全部落盘；
5. **W4 的 22 条低频、滞后或冗余序列保留 backlog**；
6. **本阶段明确 HOLD 2 条**：`unemployment_25_29` 和 `nssf_stock_snapshot`。

这套顺序服务的是当前项目最真实的研究问题：价值、低波、红利、Amihud 等长期多头候选共享较强风格暴露，且 2024—2026 明显走弱；宏观层首先应解释或约束这些策略的**条件有效性与风险暴露**，而不是另开一个“宏观裸挖 Alpha”项目。

## 2. 约束与评分口径

### 2.1 文档优先级

本项目内的约束顺序为：

```text
research/constitution/RESEARCH_CONSTITUTION.md
> 01_macro_data_research_methodology.md
> 本 R011 评估
> 02_china_macro_data_universe_v0.1.yaml（ingestion backlog）
```

YAML 的 `tier` 是参考先验，不是本轮最终执行顺序。任何序列都必须满足 PIT、信息可得时间、版本和口径断点要求；无法重建历史 vintage 时只能标为 `exploratory_only`。

### 2.2 A/B/C 评分

| 维度 | 1 分 | 3 分 | 5 分 |
|---|---|---|---|
| A 数据可得性 | 无稳定公开源/强许可障碍 | 官方公告或附件可得，但历史碎片化 | 官方结构化查询、XLS/CSV 或稳定历史下载 |
| B 研究价值 | 样本过短、滞后且与当前策略弱相关 | 可用于状态解释或辅助 Nowcast | 可直接服务 Regime、Conditional Alpha 或 Exposure Control |
| C 完整落盘时间 | 这里不用分数，直接给人日 | 包括 raw、normalized、PIT 时间、版本、manifest、基础质量门禁 | 不包括因子研究与策略回测 |

工时假设：一名熟悉仓库的高级量化数据工程师；官网访问稳定；不购买商业数据库；“完整落盘”至少包含 raw snapshot、`release_ts/available_ts/vintage_ts`、content hash、parser version、口径断点和 5 个官方历史点核对。历史 vintage 无法重建时，最终值历史与自本项目启动后的 forward vintage 必须分层保存。

## 3. 当前仓库事实：已有文件不等于宏观层已完成

当前 catalog 中已有 8 个宏观 Bronze 资产：

| 文件 | 覆盖 | 行数 | 与 YAML 的重叠 | 当前限制 |
|---|---:|---:|---|---|
| `cn_gdp.parquet` | 2016Q1—2026Q2 | 42 | GDP 总量、实际增速、二/三产业 | Tushare Bronze；非 PIT |
| `cn_cpi.parquet` | 2016M01—2026M07 | 127 | CPI 同比/环比 | 无核心 CPI；非 PIT |
| `cn_ppi.parquet` | 2016M01—2026M07 | 127 | PPI 同比/环比及部分分项 | 非 PIT |
| `cn_m.parquet` | 2016M01—2026M07 | 127 | M0/M1/M2 | 非 PIT、无口径版本 |
| `cn_pmi.parquet` | 2016M01—2026M07 | 127 | 多数 PMI 总项和分项 | 字段是源代码、语义未正式映射；非 PIT |
| `sf_month.parquet` | 2016M01—2026M07 | 127 | 社融增量/存量 | 无分项、无历史口径版本；非 PIT |
| `shibor.parquet` | 2016-01-04—2026-08-19 | 2,630 | ON/1W/3M 等期限 | catalog 标为 PIT，但尚缺 2007—2015 |
| `cn_schedule.parquet` | 仅 2026 日程 | 176 | 发布日程辅助 | 不是历史 `release_ts` 库，catalog 标为非 PIT |

粗略看，至少约 35 条 YAML 候选已有字段层面的部分重叠；但除 Shibor 外，catalog 明确标为非 PIT。当前检查也没有在宏观资产旁看到能够证明官方 raw 响应、长历史、历史发布时点、vintage 和口径断点均可重放的闭包。因此：

- 这些文件可作为**迁移 seed / 对照源**；
- 不得直接标成 `RESEARCH_READY`；
- W1 的第一目标是“升级已有资产”，不是再生成一套同名快照。

本节只是资产清单读取，不是正式数据质量审计。

## 4. 与现有策略和研究的直接关系

| 已有研究事实 | 宏观层优先回答的问题 | 最相关数据 |
|---|---|---|
| 价值、低波、红利、Amihud 长多候选高度相关，并共同暴露于小盘/低流动性风格 | 哪些信用、流动性、增长和通胀状态会放大共同回撤？ | DR007/R007、Shibor、国债曲线、M1/M2、社融、PMI、CPI/PPI |
| 价值与低波在 2024—2026 相对基准明显走弱 | 是状态变化还是策略永久失效？何时只应降 Gross Exposure？ | 信用脉冲、期限利差、PMI 新订单、地产销售、财政、外需 |
| 当前模拟仓是红利与波动趋势的 A/B 权重对照 | 宏观层只能作为慢速 overlay，不应替代已有价格趋势/波动风控 | 流动性、信用、增长、通胀四状态；先影子，不直接驱动交易 |
| 北向资金因子被记录为 regime-dependent | 外部流动性和人民币压力是否解释其时变有效性？ | 结售汇、涉外收付款、外储、贸易、期限利差 |
| 纯动量全历史稳定性不足 | 不应为“救活动量”定制宏观变量 | 仅在统一条件效应矩阵中作为对照 |

执行研究时必须遵守全局 Constitution C38：**先检验 `E[StrategyReturn | State]`，再建复杂 regime 模型**。建议先对价值、低波、红利、Amihud、动量趋势和当前 A/B 模拟仓分仓做统一的状态条件分布，而不是先训练黑箱宏观分类器。

## 5. 推荐获取顺序

### 5.1 P0：数据治理骨架（非 YAML 序列，4—7 人日）

在 W1 前必须完成：

- `source_registry`、`series_registry`、raw/vintage/feature schema；
- `observation_period/release_ts/available_ts/vintage_ts` 语义；
- 官方原文、请求参数、附件和响应的不可变 raw snapshot；
- content hash、parser version、methodology break registry；
- 累计转单月的显式白名单；
- `exploratory_only / research_ready / production_ready` 状态门禁；
- 发布后取数与数据库晚更新的双时间源配对。

没有 P0，不允许把新下载文件命名为“完整宏观库”。

### 5.2 W1：立即做，34 条，约 14—22 人日

| 顺序 | 数据包 | A | B | 完整落盘时间 | 判断与用途 |
|---:|---|---:|---:|---:|---|
| 1 | 利率与流动性 11 条 | 4 | 5 | 4—7 日 | 最适合当前 Amihud/低波/波动趋势的 Exposure Control；日频样本也最充足 |
| 2 | PMI 领先状态 8 条 | 5 | 5 | 3—5 日 | 新订单、新出口订单和价格分项用于 Growth/Inflation turning point |
| 3 | CPI/PPI 价格脊柱 5 条 | 5 | 5 | 3—5 日 | 服务通胀状态、实际利率和价值/红利条件效应 |
| 4 | 货币、贷款、社融 7 条 | 4 | 5 | 5—8 日 | 信用状态核心；需处理社融和货币口径修订 |
| 5 | GDP/工业增加值锚 3 条 | 5 | 3 | 2—4 日 | 用作状态验证目标和分母，不期待直接预测股票 |

W1 序列：

```text
gdp_nominal, gdp_real_yoy, industrial_va_yoy,
pmi_mfg, pmi_mfg_new_orders, pmi_mfg_new_export_orders,
pmi_mfg_input_price, pmi_nonmfg_activity, pmi_nonmfg_new_orders,
pmi_nonmfg_input_price, pmi_composite_output,
cpi_yoy, cpi_core_yoy, ppi_yoy, ppi_mom, ppirm_yoy,
m1_balance, m2_balance, rmb_loans_flow, corp_medium_long_loan_flow,
tsf_flow, tsf_stock, tsf_gov_bond_flow,
shibor_on, shibor_1w, shibor_3m, dr007, r007, omo_7d_rate,
mlf_1y_rate, lpr_1y, lpr_5y, gov_bond_1y, gov_bond_10y
```

W1 内部仍有两个落盘注意点：中债历史下载/使用条款需要在 source registry 保存；DR007/R007 若公开批量入口不稳定，可用现有许可数据做对照，但官方发布页仍控制定义和时间。

### 5.3 W2：W1 完成后做，26 条，约 15—25 人日

| 顺序 | 数据包 | A | B | 完整落盘时间 | 判断与用途 |
|---:|---|---:|---:|---:|---|
| 1 | 消费、投资、地产 11 条 | 4 | 5 | 7—12 日 | 中国信用—地产—需求链；70 城价格 breadth 可用于风险状态 |
| 2 | SAFE 外部流动性 5 条 | 4 | 5 | 4—7 日 | 北向/外需/人民币压力条件层；官网有时间序列和发布日程 |
| 3 | 外贸总量与关键实物 5 条 | 4 | 4 | 4—7 日 | External state 与制造业/周期品暴露；海关历史修订需版本化 |
| 4 | 财政脉冲 5 条 | 3 | 4 | 5—8 日 | 财政/土地收入对基建、地产和价值周期的条件影响；累计值处理较重 |

W2 序列：

```text
retail_sales_total, retail_catering_yoy,
fai_cum_yoy, fai_manufacturing_cum_yoy, fai_infrastructure_cum_yoy,
re_new_start_area, re_sales_area, re_sales_value, re_funds_available,
house_price_new_70, house_price_secondhand_70,
fiscal_revenue, fiscal_expenditure, gov_fund_revenue,
land_transfer_revenue, gov_fund_expenditure,
exports_usd, imports_usd, trade_balance_usd,
imports_crude_oil_volume, imports_iron_ore_volume,
fx_reserves, bank_fx_settlement, bank_fx_sales,
crossborder_receipts, crossborder_payments
```

### 5.4 W3：条件获取，61 条，约 22—35 人日

判断：**要获取，但必须在 W1/W2 的条件效应矩阵证明需要更多结构分辨率后再做。** 这些数据的主要价值是改善 Nowcast、状态解释和行业暴露，不应扩大为 61 条独立 Alpha 假设。

优先顺序：

1. 社融/贷款分项与历史政策利率；
2. PMI 库存、订单、价格、就业分项；
3. CPI/PPI、消费、投资、地产分项；
4. 税收和贸易结构；
5. 用电、货运、港口 Nowcast 代理。

W3 序列：

```text
industrial_profit_cum, industrial_capacity_util, services_production_yoy,
electricity_generation,
pmi_mfg_production, pmi_mfg_backlog, pmi_mfg_finished_inventory,
pmi_mfg_purchase_qty, pmi_mfg_imports, pmi_mfg_output_price,
pmi_mfg_raw_inventory, pmi_mfg_employment, pmi_mfg_supplier_delivery,
pmi_mfg_expectations,
retail_goods_yoy, retail_above_designated_yoy, online_retail_cum,
retail_auto_yoy, retail_home_appliance_yoy,
fai_private_cum_yoy, fai_hightech_cum_yoy, fai_electricity_cum_yoy,
fai_transport_cum_yoy,
re_investment, re_residential_invest_yoy, re_inventory_area,
re_funds_domestic_loans, re_funds_mortgage,
cpi_mom, cpi_food_yoy, cpi_nonfood_yoy, cpi_services_yoy,
ppi_means_production_yoy,
m0_balance, rmb_loans_balance, household_short_loan_flow,
household_medium_long_loan_flow, corp_short_loan_flow, bill_financing_flow,
rmb_deposits_balance, tsf_rmb_loan_flow, tsf_trust_loan_flow,
tsf_entrusted_loan_flow, tsf_corp_bond_flow,
rrr_large_banks, benchmark_loan_1y,
tax_revenue, vat_revenue, corp_income_tax, personal_income_tax,
fiscal_scitech_spend,
general_trade_exports, processing_trade_exports, exports_asean, exports_us,
power_consumption_total, power_consumption_secondary,
power_consumption_tertiary, freight_total, port_cargo, port_container
```

### 5.5 W4：保留 backlog，不在前三波投入，22 条，约 10—18 人日

判断：这些序列可得性并不一定差，但相对当前策略的边际研究价值较低，常见问题是滞后、修订高、样本短或与已有序列冗余。只有在明确的研究假设点名后才获取。

```text
gdp_qoq_sa, gdp_secondary_yoy, gdp_tertiary_yoy,
industrial_va_cum_yoy, industrial_revenue_cum,
re_completion_area, re_construction_area,
bop_current_account, bop_financial_account, external_debt,
surveyed_unemployment, surveyed_unemployment_31cities,
unemployment_16_24_ex_students, urban_new_jobs,
disposable_income_pc, percapita_consumption,
power_consumption_industry, power_consumption_residential,
freight_road, transport_fai,
nssf_assets_total, nssf_annual_investment_return
```

其中社保年度资产和收益数据很容易形成漂亮图表，但几乎不增加月频 A 股状态识别能力；它们适合制度研究，不应挤占核心宏观工程预算。

### 5.6 HOLD：本阶段不做，2 条

| 序列 | A | B | 若独立实施的时间 | 决策 |
|---|---:|---:|---:|---|
| `unemployment_25_29` | 5 | 1 | <1 日 | 2023 年末以来样本过短，无法支持当前低频策略条件研究；等待样本自然积累 |
| `nssf_stock_snapshot` | 2 | 3 | 20—40 日 | 它是 censored institutional-holdings 工程，不是宏观状态脊柱；需单独项目、股东名归一化与 visibility state machine |

`nssf_stock_snapshot` 不是永久否决。若未来明确研究 `NSSF × Quality/Low Crowding`，应新开独立轮次，不得把“退出前十大”解释成清仓。

## 6. 总体时间与停止规则

| 范围 | 单人完整落盘时间 | 产出 |
|---|---:|---|
| P0 + W1 | 18—29 人日 | 可研究的 Growth/Inflation/Credit/Liquidity 基础状态层 |
| P0 + W1 + W2 | 33—54 人日 | 五状态脊柱 + 中国信用地产财政外需传导层 |
| 再加 W3 | 55—89 人日 | 结构分项与 Nowcast 候选层 |
| 再加 W4（不含 HOLD） | 65—107 人日 | 143 条候选的完整 backlog 覆盖 |
| 单独增加 `nssf_stock_snapshot` | 另加 20—40 人日 | 机构持仓可见性数据集，不属于宏观主线 |

多 source adapter 并行可缩短日历时间，但不能绕过串行门禁：P0 schema → 单源样板 → raw 重放 → PIT 映射 → 基础质量检查 → 批量扩展。

以下条件触发停止或降级：

- 找不到可信历史 `release_ts`：历史只进 `exploratory_only`，从当前开始 forward vintage；
- 官网条款不允许批量/衍生使用：停止该路径，登记许可问题，不绕过；
- 结构分项与核心总量高度共线且不能改善 OOS nowcast/条件效应：W3 对应数据包停止；
- 宏观状态只能解释同期收益、不能稳定改善下一期风险或条件分布：不得用于动态调权，只保留监控解释；
- 任何状态规则只有全样本回看有效：不得进入模拟仓。

## 7. 后续 Agent 的首个执行任务建议

用户批准后，不要直接抓 34 条 W1。首个可验收工作单元应是：

1. 建 P0 最小 schema/registry；
2. 选 Shibor ON/1W/3M 作为日频样板，升级现有 2016+ 文件并补到 2007；
3. 选制造业 PMI/新订单作为月频发布稿 + 历史数据库配对样板；
4. 验证 raw snapshot、hash、parser version、release/available/vintage 四时间和可重放；
5. 通过后再复制 adapter 模式到 W1 其余数据包。

首个执行轮次的验收不以“下载多少行”为目标，而以“两种频率、两类官方源、严格 PIT、可重放闭包”通过为目标。

## 8. 2026-08-25 官网可得性核验摘要

- 国家统计局：[国家数据](https://data.stats.gov.cn/easyquery.htm)仍提供月度/季度/年度查询；[2026 发布日程](https://www.stats.gov.cn/sj/fbrc/bnxxfb/)给出具体日期和时间，并说明国家数据通常在正式发布约 3 个工作日后更新。
- 人民银行：[调查统计司](https://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html)继续发布金融统计和社融表；社融口径修订必须版本化。
- Shibor/LPR：[Shibor 数据服务](https://www.shibor.org/shibor/dataservices/)提供历史查询和 Excel 导出；批量与再分发边界需保存条款证据。
- 中债：[国债收益率历史数据](https://yield.chinabond.com.cn/cbweb-mn/pgxh/showHistory)可查询；应登记下载窗口、许可和曲线定义。
- 财政部：[全国财政收支情况](https://www.mof.gov.cn/zhengwuxinxi/redianzhuanti/quanguocaizhengshouzhiqingkuang/)是公告型累计数据源，历史网页和附件解析成本较高。
- 海关总署：[月度统计公报](https://english.customs.gov.cn/statics/report/monthly.html)提供总量、伙伴、贸易方式和商品表，并明确后续核实可能修订历史值。
- 外汇局：[统计数据](https://www.safe.gov.cn/safe/tjsj1/)提供跨表查询、结售汇、涉外收付款、国际收支和外储时间序列，并发布年度日程。
- 国家能源局和交通运输部继续发布月度用电、货运和港口数据；交通部近期附件包含 XLSX，适合 W3 建结构化 adapter。
- 全国社保基金会：[年度报告](https://www.ssf.gov.cn/portal/xxgk/fdzdgknr/cwbg/sbjjndbg/A0010030801index_1.htm)可回溯多年，但不提供公众可用的季度完整 A 股持仓。

## 9. 轮次与 Git 记录

- 项目轮次：R011。
- 工作分支：`codex/inverse-signal-pool-v3`。
- 本轮记录基线：`62499e242c4b9a14b8cb08f77d8db393d04aefcc`。
- 工作树在本轮开始前已有大量修改和未跟踪文件；本轮只移动 `docs/temp-Macro` 并新增本评估、更新轮次索引，不处理其他用户改动。
- `git fetch --prune origin` 因连接被重置失败；本轮没有提交、推送或回滚。
