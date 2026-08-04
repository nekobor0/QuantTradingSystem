你是执行者，本书是唯一任务来源；拿不准的写入`BLOCKED_V7.md`，继续不受影响项。断线先读`CONTEXT_HANDOFF_V7.md`、`PROGRESS_V7.md`和本书，每完成一项立刻记进度，禁止重做。目标是区分QAV只存在于不可交易微盘，还是V6的30股映射过度集中，并启动可追加的真实影子。冲突时：PIT/死亡边界 > 事前冻结 > Stage S/P门禁 > 研究完整 > 速度。“只允许/不许”违反即失败；“建议”可调整但须记理由。

## 我替领导拍的板

- 目标资本K=1000万元、最大单股2%，因此预投资池要求ADV20>=1000万元（猜的）｜更低K会高估扩容性。
- 核心排名仍用V6原始QAV；流动性中性和行业内QAV只作预注册诊断，不从三者挑最好（猜的）｜可能错过更强映射，但避免三选一。
- 100股按分数名次100…1线性权重，归一后最大1.98%；行业主动权重上限5%（猜的）｜需要确定性约束修复。
- 非线性冲击用平方根模型：5bp基础成本外，参与率2%时额外10bp（猜的）｜系数是模型风险，必须单列敏感性但不能据此改核心结果。

## 界限

只允许改/新增：`src/quant_trading_system/research/v7/capacity_aware_qav.py`、`scripts/v7/run_capacity_aware_qav_v7.py`、`tests/research/v7/test_capacity_aware_qav.py`、`artifacts/registrations/c7_capacity_aware_qav.md`、`artifacts/data_audits/c7_capacity_aware_qav.json`、`artifacts/evaluations/c7_capacity_aware_qav_*`、`artifacts/evaluations/multiple_testing_ledger_v7.csv`、`artifacts/live_shadow_v7/c7_capacity_aware_qav/**`、`PROGRESS_V7.md`、`BLOCKED_V7.md`。其余只读。不得改V6构造/结果、GOAL、公共门禁、旧账本或数据源。

## 现状与任务0

2026-08-03实测：V7+V6共96 passed；面板554,400行/96月，QAV可用370,142行；按上市250日、ADV>=1000万元后351,132行、5,023股、95月，月最少1,259股；标签与ADV均554,400行。先复跑`python -m pytest tests/research/v7 tests/research/v6 -q`，必须96 passed。核对上述文件行数与GOAL_V7哈希`88AABA...164CC4E`；不符写BLOCKED并停止受影响项。

## 任务1：登记与PIT审计

先写registration并校验：research_id、`post_v6_hypothesis=true`、唯一6月期限、全A等权主基准、一个变体、历史仅开发、月频影子至少12月。投资池固定为上市>=250交易日、非ST/退市整理、T+1可交易、近60日有效交易达标、ADV门槛；不得按交易所删除。审计重复键、公告可用日、交易/标签隔离、池覆盖、输入SHA256。失败即`DATA_BLOCKED`，不算收益。

## 任务2：Stage S再Stage P

Stage S输出raw、流动性中性、行业内QAV，但核心判定只用事前指定的可投资池6月Partial Rank IC；要求>0.03、正月>55%、流动性最高及中间层均为正。未过则`REJECTED`且不得跑Stage P。通过后构建100股单调权重，单股<=2%、单行业正主动权重<=5%、月调仓/6月核心期限、交易参与率<=2%，T+1复权开盘；保存信号、持仓、月收益和约束违规。

## 任务3：评价与合规结论

历史只给`SIGNAL_VALID/RESEARCH_SHADOW/REJECTED/DATA_BLOCKED`，不得PROMOTE。Stage P门槛：净超额>4%、IR>0.60、单股贡献<15%、1000万元容量、最近两完整年度不得同时负；成本含核心平方根冲击。追加V6的68项到账本后登记新试验，标明历史p值非确认。若历史通过，只建立append-only影子配置和空起点，不伪造2026-07后观测。

## 规矩

禁止翻号、挑三种信号最好者、改K/股票数/期限/ADV/行业上限、删北交所、skip/todo、mock被测对象、放宽断言或`|| true`。测试0 skipped；连续三次同一验收失败即停止该项。反向验证至少覆盖未来公告、ADV超限和Stage S失败仍跑Stage P，贴红→绿证据。

## 完成条件

1. `python -m scripts.v7.run_capacity_aware_qav_v7`可复算并生成registration hash、数据manifest、Stage S/P结果、账本和合规决策；2. V7+V6测试全绿且不少于96、GOAL哈希不变、白名单外零改动。PROGRESS贴实际输出和反向验证，BLOCKED空也写“无”；或三轮用尽后停止并交付可复算死因。
