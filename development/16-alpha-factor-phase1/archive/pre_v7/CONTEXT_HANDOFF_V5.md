# V5上下文压缩与续跑索引

更新时间：2026-07-30。用途：额度耗尽、电脑重启或新会话时，不依赖聊天历史继续。

## 先读顺序

1. `GOAL.md`：V5双指数增强唯一目标与硬约束。
2. `FACTOR_ZOO_59.md`：59个旧候选+3个V4候选的构造、数值和失败原因。
3. `CHECKPOINT_V4_2026-07-30.md`：T+1开盘、风格基线、财务PIT和V4产物。
4. `EVALUATOR_V4_SPEC.md`、`FUNDAMENTAL_SURPRISE_V4_SPEC.md`：不可事后修改的旧研究规格。
5. 本文“下一条动作”。

## 用户最新策略定义

- 两策略：中证1000、沪深300；母池为全部A股非退市股票。
- 最多日频调仓；每策略扣成本年化超额目标3%，年化TE 5%，绝对最大回撤≤20%。
- 月单边换手≤100%；单股≤8%，行业≤30%；相对基准Size暴露±0.25标准差；资金1000万元。
- 解释性默认及成本/ADV口径详见`GOAL.md`“我替领导拍的板”。

## 已完成事实与入口

- V4面板：`factor_panel_raw_v4_t1_open.parquet` 554,400行；`factor_panel_short_horizon_v4_t1_open.parquet` 9,009,889行。
- 风格：`factor_panel_style_baseline_v4.parquet`；活跃行Beta 96.84%、ResidualVol 95.80%、Value 99.27%、Investment 93.80%。
- 财务：`tushare/fina_indicator.parquet` 312,550行；完整性见`tushare/fina_indicator_audit.json`。
- 慢标签：`slow_horizon_labels_v4_t1_open.parquet`；核心3个月活跃覆盖94.37%。
- 新财务因子结果：`factor_evaluation_fundamental_surprise_v4.json`，三个均拒绝。
- 指数权重：`index_weight_000300_SH.parquet` 37,800行、`index_weight_000852_SH.parquet` 126,000行；均2016-01至2026-06、126个月、重复0、每期权重和约100%。
- 测试命令：`python -m pytest tests/research/alpha_phase1 -q`；当前46 passed、0 skipped。

## 第三轮反馈形成的新研究方向

停止把“至少5个单独全门槛通过”当唯一前置条件。建立风格Baseline、B级弱特征库和边际组合贡献评价器。可用角色：Value/Quality/Investment/Momentum/LowResidualVol作Baseline；`holder_concentration_level`仅尾部增强；首板/回购完成负向关系仅影子风险过滤；旧反向发现不得直接翻号生产化。累计62次试验必须进入多重检验账本。

## V5本轮新增产物与已验收数字

- `PORTFOLIO_EVALUATOR_V5_SPEC.md`：已在查看组合收益前冻结月频P0、TE/IR、换手、成本、容量和边际贡献公式。
- Tushare `index_daily`仅补两次请求：`tushare/index_daily_000300_SH.parquet`、`index_daily_000852_SH.parquet`，各2,080行，2018-01-02至2026-07-30，重复0；元数据见`index_daily_v5_manifest.json`。
- `benchmark_risk_audit_v5.json`、`benchmark_monthly_v5.parquet`、`benchmark_industry_weights_v5.parquet`：权重各96个月与面板对齐，重复0；官方T+1开盘到下期T+1开盘收益95/96个月有效，末月因未来区间未完成缺失。
- `factor_panel_style_baseline_v5.parquet`：554,400行、96个月、重复0。活跃覆盖Quality 88.73%、Leverage 88.79%、Value 99.27%、Investment 93.80%、Momentum 93.23%、LowResVol 95.80%。元数据见同名metadata。
- 基准最低Quality权重覆盖：沪深300 78.23%，中证1000 87.91%；行业最大基准权重分别24.21%、22.65%，均低于30%组合上限。
- 新增测试3项通过；全套测试仍须在本轮组合代码完成后重跑。

## 当前运行态与下一条动作

- 当前无遗留Python进程。`portfolio_execution_labels_v5.parquet`已按最终停牌计价口径完成：554,400行、重复0，活跃非末月mark覆盖99.998%。历史PID均已结束，不应再查找。
- 预期产物：`portfolio_execution_labels_v5.parquet`及metadata。完成后先核对554,400行、重复0、末月收益缺失符合预期，再构建B级库和基准相对P0组合。
- 组合模拟必须在无法卖出时保留原持仓；`mark_return_1m`即使退出日不可交易也保留作市值计价，不能把不可卖股票收益删掉。
- B级面板已完成：`b_feature_panel_v5.parquet` 554,400行、重复0；户数集中Pure覆盖75.87%，价量背离Pure覆盖78.07%，平均月度Spearman 0.155；相对Baseline的固定验证边际贡献亦已完成，结论见下一条。
- P0固定验证：沪深300净超额3.484%、TE2.069%、IR1.415、回撤-13.26%；中证1000为4.036%、3.721%、0.787、-18.10%。约束0违规、1000万元容量通过；但全历史绝对回撤均约-30%，目标未整体完成。
- 户数集中10%使两个IR升至1.467/0.849，保留B级；价量背离及联合版本降低IR，淘汰。`style_*_portfolio_v5_evaluation.json`为机器结果。
- MA200/70%风险开关已失败：全期回撤仍26%—27%，TE升破5%；禁止继续调该参数。下一条动作改为冻结ICIR/24月滚动回归合成与62次多重检验账本，再提出不同风险机制。
- 2026-07-31已完成上述下一条动作：ICIR固定验证双策略净超额均低于3%，且中证1000容量有2笔真实超限，拒绝；24月滚动回归固定验证为沪深3003.240%/TE1.767%、中证1000 3.784%/3.636%，容量与约束通过，但全历史回撤仍约30%，整体失败。
- 62次账本已落盘：严格通过0，全局BH-FDR 5%统计显著9项，但不改变经济/交易门槛拒绝。15%目标波动第二风险机制也失败，中证1000固定验证TE10.984%、净超额-2.454%。
- 三轮冻结合成/构造均未满足整体条件，复算死因见`V5_FAILURE_DIAGNOSIS_2026-07-31.md`。下一条动作是停止历史参数搜索，保留24月回归为影子候选并进入实时影子组合；若继续历史研究，必须先登记新的横截面回撤防护机制，而非现金择时。
- 本轮最终全套测试：57 passed、0 skipped；当前无遗留Python进程。

## 已知坑

- 当前工作区无Git仓库，不能依赖git回滚；冻结产物必须使用新文件名和原子替换。
- PowerShell读中文需`-Encoding UTF8`。
- 旧目标的T+1收盘和中证全指基准已被V5取代；历史证据保留但不得混用。
- Goal UI仍可能显示旧blocked；当前无外部阻塞，不能因UI状态重复抓数或误标完成。
- 不能用成分股“可交易标签收益”合成指数基准：2019-12/2020-01涨跌停会令覆盖骤降。正式基准必须用指数自身日线；成分标签覆盖只作执行诊断。
- 财报事件的120日寿命不能复用于慢速Quality，否则每年2—3月覆盖周期性接近0。V5慢风格按ann_date PIT结转最新财报、最长250天；事件面板仍保持120天冻结规则。
- 直接运行含`quant_trading_system`导入的脚本需项目`src`在Python路径中；pytest已自动配置。后台长任务可能被工具提前返回，重跑前先查Python进程和目标文件。
