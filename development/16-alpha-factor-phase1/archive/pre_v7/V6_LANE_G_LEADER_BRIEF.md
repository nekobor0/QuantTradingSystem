你是 Lane G 执行者，本文件是本轮唯一任务来源；最高约束是 `GOAL_V6.md`。中断先读 `PROGRESS_V6_LANES.md`，每项完成后更新；存疑写 `BLOCKED_V6_LANES.md`。目标是先审计可进入总组合的独立引擎；只有输入合格才运行首个固定权重配置。冲突时：独立验证资格 > 无未来信息 > 事前冻结 > 组合表现 > 速度。

## 我替领导拍的板

- 首个配置方法固定为60%指数增强、20%防御、20%独立Alpha；只在三类输入各至少1个且状态为PROMOTE/SHADOW时运行。
- 指数增强输入允许GOAL冻结的24月滚动回归当前影子基线；被`REJECTED`或`DATA_BLOCKED`的A–F候选一律不能输入。
- 独立Alpha可以来自C/D/E/F任一通过者，但不能用多只拒绝策略拼出“分散”。
- 若输入不足，Lane G正式状态为`DATA_BLOCKED`，只输出输入审计和报告，不制造退化的一引擎“总组合”。

## 界限

只允许新增 Lane G 专属模块、脚本、测试、registration、输入审计/evaluation、`V6_LANE_G_REPORT.md`及 Lane 进度/阻塞。不得改A–F决策、把V5普通基线重命名成防御/Alpha、降低总组合门槛或写影子。

## 现状与任务0

2026-08-03实测：冻结24月回归是当前影子相对收益基线；Lane A新收缩ICIR、Lane B Downside Beta、Lane C QAV、Lane D反转、Lane E残差动量、Lane F行业动量均为`REJECTED`。现有合格输入仅指数增强一类，防御和独立Alpha为0。先用机器脚本重读全部evaluation，禁止按文档摘要猜状态。

## 任务1：输入资格审计与反向验证

实现严格资格schema：每个输入必须有research_id、lane、role、decision、月收益路径、持仓路径、固定验证和成本容量证据；decision仅PROMOTE/SHADOW/冻结shadow baseline可用。要求index/defensive/independent_alpha三角色齐全，否则fail-closed为`DATA_BLOCKED`。故意把REJECTED候选加入应变红，恢复全绿。

## 任务2：条件式固定权重配置

仅当任务1 PASS才运行60/20/20；否则不得计算或报告伪总组合指标。若可运行，输出净超额、IR、回撤、下行Beta、相关性、收益分散、交易净额、成本容量、暴露及20%权重敏感性；固定验证通过后才可影子。

## 规矩

禁止纳入拒绝候选、搜索权重、对缺失角色填现金/零收益、改决策文件、skip/todo、删测试、mock核心或吞退出码。输入不足是可信结果，不是绕过理由。

## 完成条件

1. Lane G 输入资格可机器复算；三角色不足时明确`DATA_BLOCKED`并列出缺口，绝不生成总组合收益。
2. 若输入齐全，固定60/20/20组合完成全部门槛；若不齐全，A–F决策和影子历史零改动。

每条贴实际命令输出；本轮最多一次输入审计和一次条件式配置。
