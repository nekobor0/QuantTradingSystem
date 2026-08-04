# 阶段一暂停交接（2026-07-29）

## 暂停原因与恢复约束

用户要求：完成正在运行的文献公式因子轮、写完必要文档后暂停，直到收到明确的“继续”指令。当前不得继续抓取 `share_float`、`repurchase`、`margin_detail`、`pledge_*` 等新数据，也不得启动下一轮因子测试。

目标仍是阶段一原硬门槛，不因当前零通过而降低标准。恢复时先读：

1. `development/16-alpha-factor-phase1/GOAL.md`
2. `development/16-alpha-factor-phase1/CHECKPOINT_ROUND2_2026-07-29.md`
3. 本文件
4. `artifacts/alpha_phase1/factor_evaluation*.json`

每个后续子任务收口前继续执行 leader Skill 验收，并补充断点文档。

## 当前轮结果：文献公式月频持久化

来源：Kakushadze (2016), *101 Formulaic Alphas*, arXiv:1601.00991。选取不依赖每日全市场截面排名、可由现有 OHLCV/VWAP 重现的 15 个公式；为匹配月度预测，将每日公式固定取 20 日均值。整体外层 `rank` 被省略，因为统一评估器会在每个信号月做截面排名。该改写已在测试前冻结。

产物：

- `scripts/alpha_phase1/build_formulaic_factor_panel.py`
- `artifacts/alpha_phase1/factor_panel_formulaic.parquet`
- `artifacts/alpha_phase1/factor_panel_formulaic_metadata.json`
- `artifacts/alpha_phase1/factor_evaluation_formulaic.json`
- `artifacts/alpha_phase1/factor_panel_formulaic_pure.parquet`

结果：15 个候选，0 个通过全部硬门槛。

最接近的三个：

| 因子 | Pure IC | IC_IR | 正IC比例 | 延时2日IC | 近3年OOS IC | HS300 IC | ZZ500 IC | 中性化保留 | 单调相邻对 | 失败点 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| formulaic_012 | 0.0490 | 0.713 | 76.8% | 0.0455 | 0.0356 | 0.0418 | 0.0244 | 59.5% | 8/9 | 中性化衰减超过30% |
| formulaic_023 | 0.0498 | 0.599 | 73.7% | 0.0453 | 0.0291 | 0.0326 | 0.0343 | 63.1% | 6/9 | IR、单调性、中性化保留失败 |
| formulaic_033 | 0.0473 | 0.590 | 71.6% | 0.0438 | 0.0313 | -0.0016 | 0.0203 | 70.9% | 8/9 | IR略低且HS300变号 |

至此累计完成 51 个冻结候选：原始价量12、股本/财务10、资金流/股东7、估值7、文献公式15；全部保留失败证据，0 个符合入库条件。不得将“接近门槛”写成通过。

性能坑：初版 `ts_rank` 使用 Python rolling 回调，60秒未完成500只。精确终止本任务进程后改为 Pandas 原生 `rolling.rank(pct=True)`，结果等价且完成全市场。最终 `compileall` 成功，`tests/research/alpha_phase1` 为 7 passed。

## 用户指定的下一轮研究队列

以下内容来自用户，恢复后应按“异常变化、实际执行、条件事件”优先，而不是直接使用静态原始字段。

### 1. 股东户数异常集中（最高优先级）

- 原始：`HNC = -Δlog(holder_num)`。
- PIT：只从 `ann_date` 起可用，绝不能从 `end_date` 起使用。
- 升级：对 `Size + Return60 + Turnover20 + Volatility60 + Industry` 回归取残差。
- 持有期测试：20/40/60交易日；仅新公告更新；信号可做20–40日指数衰减。
- 当前差距：既有实现只对 size/industry/volatility 做统一中性化，缺少 Return60、Turnover20 和事件衰减，需要重做而非复用旧结论。

### 2. 已知解禁供给压力

- 接口：`share_float`，字段需含公告日、解禁日、解禁股数/比例、股东名、股份类型。
- 公式：在 `ann_date <= t < float_date <= t+20` 条件下，未来20日已知解禁股数之和 / `free_share_t`。
- 对原始股东、定增、高管激励、国有股东设置事前冻结权重。
- 控制：上市年限、总市值、自由流通市值、自由流通比例、Return60、Turnover20、行业。

### 3. 回购真实执行强度

- 接口：`repurchase`。
- 重点不是公告标记，而是20日内“累计实际回购金额的增量 / 自由流通市值”。
- 同一计划多次公告不能累计相加；先识别计划，再计算 `ΔAmount_t = Amount_t - Amount_{t-1}`。
- 进度权重：董事会预案低、股东大会通过中低、实施高、完成高；需在测试前冻结映射。
- 控制 Value、Momentum/长期反转、Size、Profitability。

### 4. 现金流确认的盈利变化

- 目标不是静态 CFO/NI，而是现金流变化对盈利变化的超额确认。
- 候选：行业内 `Z(ΔCFO_TTM/Assets) - Z(ΔNetIncome_TTM/Assets)`。
- 或以营收增长、净利润增长、应收变化、存货变化、行业和季节效应估计 ExpectedCFO，再用 `(CFO_TTM-ExpectedCFO_TTM)/Assets`。
- 普通 Tushare 财务接口需要逐股票抓取；恢复后先做调用量预算和断点设计。
- MvpSelect 现有部分原始现金流行缺报告日和公告日，不能用于 PIT，需要 Tushare 补采或可靠修复来源。

### 5. 异常融资需求

- 接口：`margin_detail`，历史自2010年。
- 原始：`(rzmre-rzche)/FreeMarketCap`。
- 对 `Return5 + Turnover5 + Volatility20 + Size + Industry` 回归取残差。
- 方向不要预设：分别研究1–5日延续与10–20日拥挤反转，以及与 MomentumState、ValuationState 的条件交互；每个方向与窗口必须在对应测试前登记。

### 6. 股权质押压力变化（备选）

- 接口：`pledge_stat`、`pledge_detail`。
- 优先 `ΔPledgeRatio × Drawdown60` 或 `-ΔPledgeRatio`，不使用静态质押比例。
- 控制 Size、Value、Residual Volatility、Leverage、Distress。

### 7. 龙虎榜机构相对行为（稀疏事件备选）

- 构造 `(InstitutionBuy-InstitutionSell)/DailyAmount`。
- 在同一天、同一上榜原因内去均值或标准化。
- 采用事件组合研究，不把未上榜股票统一赋0后冒充全市场高覆盖因子。

### 8. 重要股东真实交易（备选）

- 接口：`stk_holdertrade`。
- `Sign(IN/DE) × ChangeRatio × HolderWeight`；实际成交高于计划公告，高管/控股股东权重高于普通财务投资股东。
- 与回购可能相关，首批组合只选一个或先正交化。

### 用户指定的首批五类

1. Ownership：股东户数异常集中
2. Supply：已知解禁供给压力
3. Management action：回购真实执行强度
4. Fundamental confirmation：现金流确认盈利变化
5. Investor leverage demand：异常融资需求

恢复后建议先做接口权限/字段/频次的窄实调与数据量预算，再冻结每一类的公式、控制变量、持有期和缺失处理。不能因为当前结果已知而用全样本/OOS选择符号或参数。

## 当前状态

阶段一未完成，入库因子数量仍为 0/5。目标不标记 complete，也不标记 blocked；按用户指令暂停等待。
