# limit_down_reopen_survival_v6 事前登记

- `registration_date`: 2026-08-03；首次固定验证前登记
- `lane`: Lane D 底部反转
- `mechanism`: 连续封死跌停代表强制卖出和流动性枯竭；首次打开且收盘离开跌停价代表抛压衰竭；PIT质量过滤排除生存概率过低的公司。
- `capitulation`: 事件日前连续至少2个交易日OHLC一价，且收盘与当日跌停价相对误差<=0.1%。
- `selling_exhaustion`: 事件日最低价与跌停价相对误差<=0.1%，收盘至少高于跌停价0.5%，且事件日不再是一价跌停。
- `fundamental_survival`: 事件日前最近PIT月末 `baseline_quality_z>=-1`、非ST、尚未退市。
- `entry`: 事件后T+1复权开盘；T+1不可交易则事件不可实现，不延迟挑选。
- `horizons`: 核心10日；制度性报告1/3/5/10/20日，禁止挑最好。
- `matched_benchmark`: 同一事件日全A T+1可交易样本的对应窗口等权收益。
- `cost`: 事件策略往返20bp；容量按事件日成交额5%参与率。
- `validation`: 开发期2018-07-02至2023-06-30；固定验证2023-07-01至2026-06-30。
- `promotion_gates`: 固定验证10日可交易事件>=30、平均净CAR>2%、正CAR比例>55%、HAC t>1、区块bootstrap 95%下界>0、最差事件>-30%、单一股票事件贡献<=20%、100万元容量通过。
- `maximum_variants`: 1；不搜索连续日数、0.1%/0.5%阈值、质量-1、窗口、成本或匹配基准。
- `decision`: 覆盖不足为 `DATA_BLOCKED`；覆盖足但门槛失败为 `REJECTED`；不得翻号。
