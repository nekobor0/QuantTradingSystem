# downside_beta_v6 事前登记

- `research_id`: `downside_beta_v6`
- `registration_time`: `2026-07-31T00:00:00+08:00`
- `family`: 横截面防御 / Downside Beta
- `candidate`: 仅一个主候选；不启用稳健性变体
- `economic_mechanism`: 市场下跌日中与全 A 等权市场共同下跌更少的股票，具有更低的系统性下行脆弱性；在保持高权益仓位时，低配高 Downside Beta 股票应改善组合下行捕获和回撤。
- `raw_fields`: TDX 后复权日收盘价、本地全 A 等权后复权日收益、月末信号日、V5 十二项风格控制、申万一级行业、V5 T+1 可交易标签
- `formula`: `Cov(stock_return, market_return | market_return < 0) / Var(market_return | market_return < 0)`
- `window`: 252 个交易日；至少 120 个股票/市场共同有效日，且至少 30 个市场负收益日
- `direction`: Downside Beta 越低越好；组合分数取其负向
- `universe`: 冻结 V5 沪深300与中证1000月末评价股票池；上市至少90日、非ST、未退市、T+1可交易
- `core_horizon`: 月频，T 月末收盘可见，T+1 开盘进入，持有至下一月评价点
- `signal_outputs`: raw、横截面1%/99% winsorized、横截面标准化、对十二项风格与申万一级行业中性化的信号全部保留
- `primary_evaluator`: 防御评价器；固定验证期下跌市场月平均相对收益
- `baseline`: 冻结 V5 `rolling_regression_24m`
- `candidate_blend`: `0.80 * V5 rolling_regression_24m score + 0.20 * standardized neutralized defensive score`；权重不得依据结果修改
- `split`: 训练期截至 2023-06-30；固定验证期自 2023-07-01 起
- `cost`: 单边换手按 5bp；另报告 10bp、20bp 压力
- `neutralization`: size、nonlinear_size、beta、momentum、short_reversal、liquidity、residual_volatility、value_composite、investment、quality_composite、leverage、loss_dummy，加申万一级行业
- `promotion_gates`: 固定验证期下跌月份平均相对收益>0；相对基线 Downside Beta 至少下降0.05；基准主要回撤阶段组合回撤至少改善3个百分点；全期净超额不得显著为负；TE不超过5%；换手、容量、个股8%、行业30%、规模暴露约束全部通过
- `maximum_variants`: 1 主候选 + 0 稳健性变体
- `future_information_rule`: 仅使用信号日当日及以前日收益和当日已冻结 PIT 控制；不得回看验证结果改窗口、方向、权重或股票池

