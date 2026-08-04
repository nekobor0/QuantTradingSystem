你是执行者，本书是唯一任务来源；拿不准写入`BLOCKED_V7.md`并继续不受影响项。断线先读`CONTEXT_HANDOFF_V7.md`、`PROGRESS_V7.md`和本书，做完一项立刻记进度。目标是检验PIT行业盈利改善广度能否为中证1000冻结Lane A基线提供独立于价格动量的10%行业overlay。冲突时：PIT/字段语义 > Stage S/P门禁 > 基准专属性 > 收益 > 速度。只允许/不许为硬约束；建议可调整但须记理由。

## 我替领导拍的板

- 唯一主基准中证1000，核心期限3个月，`BENCHMARK_SPECIFIC`；沪深300只作外部诊断，不参与晋级。
- 四项等权且不得事后删改：营收同比加速度为本季`q_sales_yoy`减上季；扣非利润同比加速度为本季`dt_netprofit_yoy`减上季；ROE改善为本季`q_roe`减上季；盈利上修来自`report_rc`卖方预测，以每个机构最新报告的下一年度Q4预测净利润构造90日公司共识，相对上月同一目标年度的对数变化；每年1月目标年度切换时该项缺失而非硬接（猜的）｜财报`update_flag`不是有时间顺序的分析师上修。
- 行业内公司项先winsorize；前三项按正值公司占比，修订项按公告时可见总市值加权中位数；卖方项每行业至少5家公司且覆盖当月成分市值20%，四项跨行业zscore后等权（猜的）。
- Stage S主门槛：未来3个月行业Rank IC>0.05；同时要求至少60个月、每月>=15个有效行业、四组件行业覆盖>=80%、正IC月份>55%、对冻结11月行业价格动量增量Partial IC>0（猜的）。
- Stage P固定90% Lane A 24月滚动回归基线+10% F7 overlay，行业主动权重上限2%、主动绝对权重和固定；目标资本1000万元、5% ADV（猜的）。

## 界限

只允许改/新增：`src/quant_trading_system/research/v7/industry_earnings_diffusion.py`、`scripts/v7/backfill_f7_financials.py`、`scripts/v7/run_industry_earnings_diffusion_v7.py`、`tests/research/v7/test_industry_earnings_diffusion.py`、`artifacts/registrations/f7_industry_earnings_diffusion.md`、`artifacts/data_backfill_v7/f7_financials/**`、`artifacts/data_audits/f7_industry_earnings_diffusion.json`、`artifacts/evaluations/f7_industry_earnings_diffusion_*`、V7账本、`artifacts/live_shadow_v7/f7_industry_earnings_diffusion/**`、`PROGRESS_V7.md`、`BLOCKED_V7.md`。其余只读。不得改GOAL、C7/B7结论、公共门禁、V6账本/产物或现有Tushare parquet。

## 现状与任务0

2026-08-03实测：中证1000权重2016-01—2026-06共126月、2,700只历史股票；财务补数已完成2,700分片/194,590行。`report_rc`按000001.SZ过滤可用，但账户限频1次/分钟、10次/小时、10次/天。F7执行标签始于2018-07，因此正式卖方补数只取2018-04—2026-07的100个月，约需20个自然日；程序必须跨日断点续跑。财报重复版本几乎同日，禁止当作上修。请求日志不得写token；字段/权限或四组件覆盖失败即`DATA_BLOCKED`，不得用净利润、普通ROE或相邻季度增长替代。

## 任务1：登记、不可变补数与PIT审计

结果前写registration：`post_v6_hypothesis=true`、唯一3月期限/000852.SH、四项固定、历史仅development、12月live、trial=71。财务补数按股票、卖方预测按报告月写immutable分片、manifest/hash/请求参数/重试记录，可断点续跑且不覆盖成功分片。信号月只读取`ann_date/report_date<=signal_date`；行业归属按申万一级`in_date/out_date`PIT，中证1000成分和市值也按当月PIT。审计重复键、公告倒序、未来泄漏、字段非空率、行业/月覆盖、预测机构/股票/目标年覆盖及异常修订分母；失败即DATA_BLOCKED。

## 任务2：Stage S门禁

在中证1000当月历史成分内构造四组件及冻结等权复合分数；未来3个月行业收益以月末后首个可交易日开盘进入计算。输出总体/年度/组件Rank IC、正月占比、HAC t/p、对行业价格动量控制后的Partial IC和行业贡献。四项或年份不得择优。主门槛及覆盖门槛任一失败即REJECTED，不运行Stage P。

## 任务3：Stage P与影子边界

Stage S通过后才运行90/10组合：T+1复权开盘、月更3月重叠持有、5bp及10/20bp压力、真实停牌/ST/退市/涨跌停、行业主动上限2%、TE和容量硬约束。相对Lane A同时要求Delta IR>0.15、年化净超额增量>1%、TE增量<1.5%、主动最大回撤不恶化超过2个百分点、容量通过且收益不由单一行业主导。历史通过最多`RESEARCH_SHADOW`，只建立空append-only配置，12月实时后才可确认。

## 规矩与完成条件

禁止翻号、字段偷换、回填后用最终版本覆盖首报、按结果改行业数/权重、迁移主基准、skip/todo、mock或放宽断言。反向验证至少覆盖未来公告不改旧信号、最终修订不可提前可见、非成分股排除、Stage S失败不运行P、单行业主导不晋级；贴红→绿。完成须`python -m scripts.v7.run_industry_earnings_diffusion_v7`生成registration hash、数据manifest、S/P、账本、报告和合规决策；V7+V6全绿、GOAL哈希不变、白名单外零改动。三次同因失败则停止该项并交付死因。
