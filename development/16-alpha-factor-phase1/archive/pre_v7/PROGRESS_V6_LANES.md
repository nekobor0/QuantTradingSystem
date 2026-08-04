# V6 Lane A–G 执行进度

更新时间：2026-08-03（Asia/Shanghai）

## 开工回执

- 目标：逐条审计并完成 Lane A–G 的独立研究闭环和 Markdown 报告。
- 顺序：A → C → D → E → F → G；B 已完成首轮研究闭环，统一补报告索引。
- 最大风险：把共享基础设施或 V5 历史资产误算为某个 Lane 已完成；G 在上游没有合格引擎时不得空转晋级。
- 当前事实：只有 `downside_beta_v6` 有完整 V6 registration/evaluation；其决策为 `REJECTED`。
- Lane A 当前任务书：`V6_LANE_A_LEADER_BRIEF.md`；本轮只允许收缩 ICIR，固定 60 月等效先验。

## 当前状态

- Lane A：`shrunken_icir_v6`已按任务书完成唯一一次正式验证，数据审计PASS，决策`REJECTED`。相对24月回归，沪深300/中证1000年化净超额分别下降0.62/1.03pp，IR下降0.599/0.388；无影子写入。
- Lane B：Downside Beta 首轮闭环完成，结果 `REJECTED`。
- Lane C：`quality_adjusted_value_v6`已完成正式验证，6个月Rank IC=0.0847、HAC t=1.929，年化净超额12.19%；但最低容量约74万元、1000万元有6笔超5% ADV，单股贡献26.1%超门槛，决策`REJECTED`。
- Lane D：`limit_down_reopen_survival_v6`已完成；153个存续事件，固定验证10日可交易事件44个，平均净CAR=-1.33%、HAC t=-0.647、最差-34.64%，五窗口均值全负，决策`REJECTED`。
- Lane E：`industry_residual_momentum_v6`已完成；3个月Rank IC=0.0203、HAC t=1.087，但年化净超额2.62%、Sharpe0.548、最差月-23.55%、单股贡献33.4%，决策`REJECTED`。
- Lane F：`industry_relative_momentum_v6`已完成；行业Rank IC=0.0671、HAC t=1.176，年化净超额4.11%，但IR0.335、主动回撤-16.30%、容量约396万元，且叠加沪深300基线ΔIR=-0.223，决策`REJECTED`。
- Lane G：输入资格审计完成，7个输入仅24月滚动回归冻结影子基线合格；缺`defensive`和`independent_alpha`，正式状态`DATA_BLOCKED`、`portfolio_computed=false`。

## Lane A 验收证据

- registration：`artifacts/registrations/shrunken_icir_v6.md`，SHA256=`647c124dc9ceff57cd3b04b069346aca94246a55a786fa5db67afd0e0409ce9b`。
- 数据：554,400行、5,775股、96月、重复0、未来信息违规0、权重和最大误差2.22e-16。
- 反向验证：内存构造未来`exit_date`后断言以`future label leakage detected`变红；恢复后4 tests passed。
- 机器结果：`artifacts/evaluations/shrunken_icir_v6_evaluation.json`；报告：`V6_LANE_A_REPORT.md`。

## 最终验收

- A–F六个正式冻结构造均已完成registration、数据审计、评价、账本与`REJECTED`决策；G输入审计为`DATA_BLOCKED`且未计算伪组合。
- 7/7 Lane报告齐全；总验收为`V6_LANES_A_G_FINAL_ACCEPTANCE_2026-08-03.md`。
- GOAL SHA256未漂移；三基线registry PASS；多重检验账本68项。
- V6测试77 passed；全仓1,639 passed。
- GOAL成功条件未满足，但本轮六个冻结构造均有可复算死因，按第19节失败路径结束无边界搜索。
