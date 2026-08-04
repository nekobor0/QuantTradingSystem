# quality_adjusted_value_v6 事前登记

- `registration_date`: 2026-08-03；首次固定验证前登记
- `lane`: Lane C2 集中式基本面策略
- `mechanism`: 市场把低估值公司中的暂时困境与永久价值陷阱混在一起；只惩罚低质量的价值分，可保留便宜且具存续质量的股票。
- `participants`: 依赖简单估值排序的系统资金与对低质量公司反应不足的基本面投资者。
- `raw_formula`: `baseline_value_z - max(-baseline_quality_z, 0)`；高质量不额外加分，低质量只惩罚。
- `direction`: 分数越高越好；禁止翻号。
- `universe`: PIT 全A可交易池；上市满90天、非ST、未退市、T+1开盘可交易、ADV20>0，Value和Quality均可用。
- `portfolio`: 30股等权；季度末冻结排名；单行业最多6股。
- `deterioration_exit`: 月末最新PIT `baseline_quality_z < -1` 或不再满足可交易/上市/ST条件时退出；不可交易则保留到可交易。
- `replacement`: 仅按最近一次季度冻结排名顺延，不使用季度后新分数追涨。
- `signal_and_execution`: T月末，T+1复权开盘；月度记录，季度重建。
- `core_horizon`: 6个月Rank IC；只用 `forward_return_6m` 做评价，不能参与选股。
- `benchmark`: 同月同可交易全A股票池的等权1个月收益。
- `costs`: 5bp基础；10bp/20bp压力。
- `validation`: 2023-07-01至2026-06-30；6个月标签只评价截至2025-12-31已有完整结果的信号。
- `promotion_gates`: 固定验证年化净超额>3%、Sharpe>0.75、20bp后净超额>0、最大回撤不比全A基准差5个百分点以上、任一行业权重<=25%、任一股票对累计超额贡献<=20%、1000万元容量通过、6个月Rank IC>0且HAC t>1.0。
- `maximum_variants`: 1；不搜索公式、30股、6个月、季度频率、行业6股、质量-1阈值或基准。
- `decision`: 未过全部门槛即 `REJECTED`，不得调参或写影子。
