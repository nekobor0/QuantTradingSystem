# 阶段一 V3 断点记录（2026-07-30）

## 当前目标

按 `EVALUATOR_V3_SPEC.md` 的物种化评价器继续挖掘A股纯多头Alpha。评价机制以《现有因子动物园分析反馈》为主：稠密、尾部、事件、条件、短周期信号分别使用适配门槛；所有假设、方向、状态和核心持有期必须在看结果前冻结。当前尚无新增入库因子，不得为了满足“至少5个”而放宽门槛。

## 已完成工作

1. 59个旧候选中重评4个错配代表：`holder_concentration_level`仍为`RESPECIFY`；`formulaic_012`进入短周期复验后拒绝；`price_volume_divergence`短周期核心无效，保留条件型重构资格；`conservative_equity_growth`仅作风格基线。
2. 补齐日频 `daily_basic`：9,102,372行、1,958日、5,778只证券、重复0。
3. 历史ST有18个接口固定缺口日，不插值、不当成无ST，统一排除；可用1,940日，明细见 `stock_st_full_available_manifest.json`。
4. `formulaic_012_daily` 5日净超额-0.110%、HAC t=-3.12、日单边换手83.3%，拒绝且不翻号。
5. `price_volume_divergence_5d` 5日净超额-0.025%、HAC t=-1.06、日单边换手42.2%，核心无效。
6. `holder_surprise_60d` 无条件及横盘条件Pure尾部均无效，拒绝。
7. 补齐官方 `stk_limit`：11,378,622行、1,958日、8,438个代码、重复0、日历差集0。严格首板事件95,266个；`first_sealed_limit_up` 核心5日匹配CAR -1.041%、HAC t=-7.43，原正向延续假设拒绝，不得结果后翻号。
8. 融资明细在冻结研究窗口内完整：5,376,724行、1,939日、5,079只股票、重复0。五个事前冻结的月频尾部变体Pure收益全部为负（-0.083%至-0.229%，t=-0.34至-1.05），均拒绝；近3年虽均转正，但不能事后截样本。异常融资机制仅保留另行登记短周期研究的资格。
9. 将旧月频回购因子按事件物种重构：物质性完成回购事件12,835个，核心20日匹配CAR -0.556%、HAC t=-2.89，事前正向假设拒绝且不得翻号。
10. 旧 `holder_conviction_120` 身份权重失效：源字段为 `C/G/P`，旧代码搜索中文，权重实际全为1。新构造物质性重要股东净增持事件5,086个，核心20日匹配CAR -0.226%、HAC t=-1.03，拒绝。

## 关键产物

- 评价规范：`development/16-alpha-factor-phase1/EVALUATOR_V3_SPEC.md`
- 因子动物园：`development/16-alpha-factor-phase1/FACTOR_ZOO_59.md`
- 日频面板：`artifacts/alpha_phase1/factor_panel_short_horizon_v3.parquet`
- Pure日频面板：`artifacts/alpha_phase1/factor_panel_pure_short_horizon_v3.parquet`
- 官方涨跌停价：`artifacts/alpha_phase1/tushare/stk_limit_full.parquet`
- 严格首板事件：`artifacts/alpha_phase1/limit_events_v3.parquet`
- 机器评价：
  - `factor_evaluation_respecified_v3.json`
  - `factor_evaluation_short_horizon_v3.json`
  - `factor_evaluation_holder_surprise_v3.json`
  - `factor_evaluation_limit_event_v3.json`
  - `factor_evaluation_margin_v3.json`
  - `factor_evaluation_repurchase_completion_event_v3.json`
  - `factor_evaluation_holder_net_purchase_event_v3.json`

## 数据缺口与禁止事项

- 18个 `stock_st` 源缺口日必须继续整体排除，禁止前后填充。
- `stk_limit` 原代码0.011元容差已修正为0.001元；禁止恢复“一分钱以内算封板”。
- 所有收益必须使用T日信号、T+1可交易价格进入，并计固定双边万分之五。
- 已看到结果的候选不得翻号、改核心持有期或事后发明状态；任何新机制必须另立名称、事前登记并使用独立证据。
- `holder_type` 的 `C/G/P` 代码在获得权威映射前不得擅自解释；旧中文关键词权重实现不能再用于研究。

## 下一步

优先从反馈建议的独立经济机制继续：已知解禁供给压力、回购真实执行强度、异常融资需求、质押压力变化、重要股东真实交易。先审计现有Tushare缓存覆盖与PIT字段，再选择数据可用且尚未被结果污染的候选，冻结公式、方向、核心窗口、风格控制和样本外切分后运行。
