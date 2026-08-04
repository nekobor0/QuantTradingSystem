你是执行者，本书是唯一任务来源；拿不准写入`BLOCKED_V7.md`并继续不受影响项。断线先读`CONTEXT_HANDOFF_V7.md`、`PROGRESS_V7.md`和本书，做完一项立刻记进度。目标是检验流动性脆弱性是否能在不明显损害全期收益的前提下降低两类指数增强的下行风险，并最短路径提供defensive输入。冲突时：PIT/死亡边界 > Stage S/P门禁 > 防御真实性 > 收益 > 速度。只允许/不许为硬约束；建议可调整但须记理由。

## 我替领导拍的板

- 核心期限1个月；日信号窗固定20/60/252日（猜的）｜不同窗口会新增搜索自由度。
- 三项脆弱性等权：`log(Amihud20/Amihud252)`、`-log(Amount20/Amount60)`、`DownDayVol60/AllDayVol60`（猜的）｜可能遗漏价差，但本地无历史盘口。
- Stage S要求下跌月1个月Partial IC>0、正IC月>55%、与普通Beta相关中位数<0.6（猜的）｜防止只做Beta换皮。
- 组合沿用两个冻结的24月回归基线，80%基线分数+20%防御分数；1000万元、5% ADV（猜的）｜与V6防御评价保持可比。

## 界限

只允许改/新增：`src/quant_trading_system/research/v7/liquidity_fragility.py`、`scripts/v7/run_liquidity_fragility_v7.py`、`tests/research/v7/test_liquidity_fragility.py`、`artifacts/registrations/b7_liquidity_fragility.md`、`artifacts/data_audits/b7_liquidity_fragility.json`、`artifacts/evaluations/b7_liquidity_fragility_*`、V7账本、`artifacts/live_shadow_v7/b7_liquidity_fragility/**`、`PROGRESS_V7.md`、`BLOCKED_V7.md`。其余只读。不得改Downside Beta、C7、GOAL、公共门禁、V6账本/产物或TDX原始JSON。

## 现状与任务0

2026-08-03实测：TDX审计8,845文件，选中5,533只/14,916,622行，A股覆盖99.84%，8个拒绝文件已有审计；全A市场收益5,236日（2005-01-05—2026-07-28）；执行面板554,400行；V7 29 tests。先跑`python -m pytest tests/research/v7 tests/research/v6 -q`并核对GOAL哈希`88AABA...164CC4E`。对不上写BLOCKED，停止受影响项。

## 任务1：登记、日信号与PIT审计

结果前写registration：新机制不是Downside Beta近义窗口；`post_v6_hypothesis=true`；RISK_FILTER候选；唯一1月期限；两个基准各自必须通过；历史仅开发；影子至少12月。用审计选中的不可变TDX文件解析复权收盘和Amount万元×10000，只用signal_date及以前数据；市场下跌日由冻结全A日收益<0定义。每组件截面winsorize/zscore后等权，脆弱性越低分数越高。审计原始hash、重复日期、窗口最小观测、覆盖和未来违规；失败即DATA_BLOCKED。

## 任务2：Stage S门禁

把复合防御分数对历史PIT行业、log(size)、普通Beta残差化，只用未来1月收益评价；核心样本仅下一月全A等权收益<0的月份。门槛：Partial Rank IC>0、正月>55%、复合脆弱性与普通Beta月度截面Spearman绝对中位数<0.6。三组件分别输出但不得挑最好。Stage S失败即REJECTED，不运行Stage P。

## 任务3：Stage P防御评价

Stage S通过后，用现有约束构造器对沪深300/中证1000分别运行80/20，T+1复权开盘、5bp及10/20bp压力、真实不可交易、换手和容量。两基准均要求：下跌月相对基线收益>0；下行捕获率下降>=5个百分点；登记的主要回撤期改善>=3个百分点；全期年化净超额增量>=-1%；TE增量<1.5%；普通Beta相关门槛保持。任何一项或容量/约束失败均REJECTED。历史通过最多RESEARCH_SHADOW，只建立空append-only配置。

## 规矩

禁止翻号、改窗口/权重、按结果删危机月、只留有利基准、把负收益称空头、skip/todo、mock对象、放宽断言或`|| true`。反向验证至少覆盖追加未来日不改旧信号、普通Beta相关超限、单一基准失败仍晋级；贴红→绿。连续三次同一验收失败即停该项。

## 完成条件

1. `python -m scripts.v7.run_liquidity_fragility_v7`生成registration hash、数据manifest、Stage S/P、两基准防御指标、账本和合规决策；2. V7+V6测试全绿且不少于106、GOAL哈希不变、白名单外零改动。PROGRESS贴命令与反向验证，BLOCKED空也写“无”；或三轮用尽后停并交付死因。
