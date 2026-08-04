# industry_residual_momentum_v6 事前登记

- `registration_date`: 2026-08-03；首次固定验证前登记
- `lane`: Lane E 股票动量
- `mechanism`: 同行业公司信息扩散速度不同；剥离行业、规模、Beta和残差波动后，个股12-1相对趋势应继续反映渐进信息吸收。
- `raw_signal`: 冻结面板 `momentum`（12-1）。
- `residualization`: 每月1%/99% winsorize、标准化，再对行业哑变量、log市值、Beta、residual_volatility做截面OLS；残差为正式方向，越高越好。
- `universe`: PIT全A可交易池；上市满90天、非ST、未退市、T+1可交易、ADV20>0且控制完整。
- `portfolio`: 每月50股等权；每行业最多5股。
- `core_horizon`: 3个月Rank IC；不比较6-1或其他持有期。
- `benchmark`: 同月同可交易全A股票池等权1个月收益。
- `costs`: 5bp基础，10bp/20bp压力；容量按5% ADV。
- `validation`: 2023-07-01至2026-06-30；3个月标签只在完整兑现行评价。
- `promotion_gates`: 年化净超额>5%、Sharpe>0.75、3个月Rank IC>0且HAC t>1、20bp后净超额>0、最差月>-20%、月均单边换手<50%、行业权重<=15%、单股累计超额贡献<=15%、1000万元容量通过。
- `maximum_variants`: 1；不搜索回看、股票数、中性化、行业上限、窗口或方向。
- `decision`: 未过全部门槛即 `REJECTED`；无影子写入。
