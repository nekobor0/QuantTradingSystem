# V6 Lane A–G 启动前审计 — 2026-08-03

## 技术摘要

V6 先前只完成了共享 Phase 1 基础设施和 Lane B 的首轮 Downside Beta 研究切片，并未完成 Lane A–G 全部研究通道。当前正式证据只有三个冻结的 V5 指数增强基线、一个 `downside_beta_v6` 事前登记及其 `REJECTED` 机器结果。其余 Lane 没有独立 registration、评价 artifact 或标准报告，不能以“已有共享评价器”代替“研究已经做过”。

## Lane 状态总览

| Lane | 原始职责 | 已有直接证据 | 研究 loop | 目标状态 | 下一步 |
|---|---|---|---|---|---|
| A 指数增强 | 低 TE、多因子净超额 | 三个 V5 基线已冻结；固定验证指标已复算 | 未发现 V6 新方法登记、边际评价或 Lane 报告 | `PARTIAL` | 先研究事前冻结的收缩 ICIR，再与三基线比较 |
| B 横截面防御 | 降低下行 Beta、尾损和回撤 | `downside_beta_v6` registration、信号、持仓、评价、账本和报告齐全 | 首个机制完整闭环，结果 `REJECTED` | `RESEARCH_LOOP_COMPLETE / ENGINE_NOT_ACHIEVED` | 保留否决；下一家族只能按新任务书另开 |
| C 系统化基本面 | 3–12 个月基本面 Alpha | 仅有 V5 风格/盈利意外历史资产，不是 V6 Lane C 研究 | 未开始 | `NOT_STARTED` | 优先 Quality-adjusted Value |
| D 底部反转 | 强制卖出—抛压衰竭—基本面存续 | 有事件数据基础，但无三段机制信号及事件评价 | 未开始 | `NOT_STARTED` | 按 GOAL Phase 5 冻结单一事件定义 |
| E 股票动量 | 行业内残差/基本面/事件动量 | 普通 momentum 是 V5 风格基线，不能充当 Lane E 独立研究 | 未开始 | `NOT_STARTED` | 优先行业内残差动量 |
| F 行业轮动 | 行业主动配置 | 现有 `construct_industry_rotation_target` 实为行业内选股并保持行业权重，不是行业轮动 | 未开始 | `NOT_STARTED` | 优先行业相对动量 |
| G 总组合 | 配置独立验证的引擎 | 交易净额、增量评价和影子接口已完成，但没有合格输入引擎集合 | 未开始且受上游约束 | `UPSTREAM_BLOCKED` | A–F 形成可用引擎后再冻结一种配置法 |

## 核心证据

- `artifacts/registrations/` 当前只有 `downside_beta_v6.md` 和三基线 registry。
- `artifacts/evaluations/` 当前只有 Downside Beta 的 V6 信号、持仓、月度收益、评价与报告。
- Lane B 完整复算覆盖 554,400 行、5,775 股、96 个信号月，重复键和未来信息违规均为 0；但两个基准的 Downside Beta 和主要回撤门槛均失败。
- Lane A 的三个冻结基线在固定验证期有正净超额，但 GOAL 同时要求 V6 新方法报告相对基线的边际贡献、年度/行业集中度、容量和实时影子证据；该闭环尚不存在。
- Lane G 明确禁止未经独立验证的候选进入，因此不能用空壳配置器或共享接口宣称完成。

## 完成口径

每个 Lane 至少需要：事前登记、数据审计、信号/目标持仓、适配的单体评价、边际组合评价、冻结稳健性与成本容量、试验账本、正式决策、固定复算命令和独立 Markdown 报告。研究结果可以是 `PROMOTE`、`SHADOW`、`DATA_BLOCKED` 或 `REJECTED`；真实否决算完成一轮研究，但不等于该引擎达到 V6 成功条件。

## 限制与后续顺序

按依赖顺序执行 A → C → D → E → F → G；Lane B 已有报告，仅补充到统一 Lane 报告索引。每个尚未开始的 Lane 在动工前单独生成 leader 任务书。G 必须最后执行，且只接收已独立验证或进入影子的上游引擎。
