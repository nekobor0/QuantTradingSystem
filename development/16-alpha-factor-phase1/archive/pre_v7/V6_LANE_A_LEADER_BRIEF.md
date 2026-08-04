你是 Lane A 执行者，本文件是本轮唯一任务来源；最高约束是 `GOAL_V6.md`。中断先读 `PROGRESS_V6_LANES.md`，每完成一项立即更新；拿不准写 `BLOCKED_V6_LANES.md` 后继续不受影响部分。目标是在冻结 V5 交易、数据和验证口径下，只研究一个“带收缩的 ICIR”指数增强方法，并对沪深300和中证1000给出可复算决策。冲突时：无未来信息 > 冻结登记 > 可交易性 > 经济价值 > 速度。只有“只允许/禁止”是硬约束。

## 我替领导拍的板

- 本轮只做 GOAL 优先级第1项“带收缩的 ICIR”，不同时测试 Ridge、窗口、权重上限或训练长度。
- 收缩目标取五风格等权；收缩强度固定为 `history_months / (history_months + 60)`（60 为事前冻结的等效先验月数，猜的）｜过强或过弱会使本构造被否决，但不允许结果后改值。
- 24个月为最小历史期，之后使用截至信号日已出结果的扩展 IC 历史；方向、股票池、T+1开盘、5bp最低成本和固定验证期全部继承 V5。
- 主比较基线为 24月滚动回归，另完整报告五风格等权与历史 ICIR；两基准均须通过才晋级。

## 界限

只允许新增/修改：`src/quant_trading_system/research/v6/index_enhancement.py`、`scripts/v6/run_shrunken_icir_v6.py`、`tests/research/v6/test_index_enhancement.py`、`artifacts/registrations/shrunken_icir_v6.md`、`artifacts/data_audits/shrunken_icir_v6.json`、`artifacts/evaluations/shrunken_icir_v6_*`、`development/16-alpha-factor-phase1/V6_LANE_A_REPORT.md`、Lane 进度/阻塞文件。V5 代码、V5 artifacts、GOAL、评价门槛和测试判卷文件只读；禁止发布生产或写实时影子，除非正式决策为 SHADOW/PROMOTE。

## 现状与任务0

2026-08-03 实测：三基线 registry 为 PASS；固定验证期 35 个月。24月回归在沪深300/中证1000的年化净超额为 3.24%/3.78%，IR 为 1.585/0.765，TE 为 1.77%/3.64%。当前没有 Lane A V6 registration/evaluation。先运行 `python -m scripts.v6.freeze_v5_baselines --check` 与 V6 测试；不符则写阻塞，只做文档审计。核对后把目标、顺序、最大风险写入进度。

## 任务1：事前登记与实现

先落盘 registration，再实现 expanding ICIR 向等权收缩；必须用 `exit_date <= signal_date` 防标签泄漏，并保存每月原始 ICIR、收缩系数、最终权重和最近可用月份。信号构造复用冻结 V5 panel 和组合执行，不改股票池、主动比例、成本、容量或约束。

验收：单测覆盖无未来信息、权重和为1、无历史时等权、60月收缩系数0.5；故意让未来月份进入一次应失败，恢复后全绿。

## 任务2：正式评价与决策

只运行一次固定验证。输出两基准的净超额、TE、IR、主动回撤、月胜率、年度贡献、换手、容量、约束、5/10/20bp成本压力，以及相对三基线的边际值。PROMOTE 要求两基准同时满足：年化净超额>2%、IR>0.75、TE≤5%、20bp压力净超额>0、1000万元容量与约束通过、无单一年份贡献>50%，且相对24月回归的净超额和IR均严格改善；否则 `REJECTED`，不得调参。

## 规矩

禁止 skip/todo、删测试、放宽断言、mock核心、改冻结切分/方向/60月先验、挑基准或吞退出码。结果变差如实保留；同一验收连败3次换项。所有机器结果原子写入新文件，不能覆盖 V5。

## 完成条件

1. `shrunken_icir_v6` 从 registration、数据审计、权重审计、两基准组合评价、容量/成本/年度集中度、账本到正式决策均可由一条固定命令复算。
2. V5 registry 指纹不变、V6及全仓测试不退化；未通过门槛时决策必须为 `REJECTED` 且无影子写入。

每条都要贴实际命令输出；`BLOCKED_V6_LANES.md` 空也写“无”。最多一轮正式固定验证，满轮即停并如实报告。
