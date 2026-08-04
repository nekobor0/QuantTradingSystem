# industry_relative_momentum_v6 事前登记

- `registration_date`: 2026-08-03；首次固定验证前登记
- `lane`: Lane F 行业轮动
- `mechanism`: 行业层面的盈利/订单与资金信息扩散慢于个股交易，近期相对强势行业在下一个月继续获得主动收益。
- `industry_return`: 每个PIT一级行业内，当月可交易股票T+1开盘到下一月T+1开盘收益等权。
- `signal`: 对每个行业取最近11个 `exit_date<=signal_date` 的已实现月收益复合值，再减31行业截面均值；越高越好。
- `allocation`: 每月前5行业等权，每行业20%；行业内当月全部可交易成员等权，不做个股Alpha选择。
- `benchmark`: 31行业等权，行业内可交易成员等权。
- `core_horizon`: 1个月行业Rank IC与配置收益。
- `execution`: T月末信号、T+1复权开盘；基础5bp，10/20bp压力；5% ADV容量。
- `validation`: 2023-07-01至2026-06-30。
- `marginal_test`: 将行业策略主动收益以20%叠加到两套24月滚动回归增强基线，要求两者ΔIR>0。
- `promotion_gates`: 年化净超额>3%、IR>0.5、行业1个月Rank IC>0且HAC t>1、20bp后净超额>0、主动最大回撤>-10%、月均换手<50%、行业权重<=25%、1000万元容量通过、两增强基线20%叠加ΔIR均>0。
- `maximum_variants`: 1；不搜索历史月数、行业数、权重、跳过期、基准或叠加比例。
- `decision`: 未过全部门槛即 `REJECTED`；不得行业中性化后另作解释。
