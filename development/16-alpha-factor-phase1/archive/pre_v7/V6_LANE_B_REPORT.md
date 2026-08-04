# Lane B 横截面防御研究报告：Downside Beta 构造被证伪

## 技术摘要

Lane B 的首轮 `downside_beta_v6` 已完成事前登记、数据审计、信号、组合、边际评价、容量、多重检验和正式决策，结论为 `REJECTED`。它没有降低下行风险：相对24月滚动回归基线，固定验证期 Downside Beta 在沪深300/中证1000分别上升0.011/0.026，主要基准回撤阶段收益分别恶化0.74/2.31个百分点。该候选没有进入实时影子。

## 冻结防御门槛在两个基准上均失败

| 基准 | 下跌月平均主动收益变化 | Downside Beta变化 | 主要回撤阶段改善 | 结论 |
|---|---:|---:|---:|---|
| 沪深300 | 不利 | +0.011 | -0.74pp | FAIL |
| 中证1000 | 不利 | +0.026 | -2.31pp | FAIL |

GOAL 要求 Downside Beta 至少下降0.05、主要回撤至少改善3个百分点，并且不显著破坏净超额、TE、成本和容量。候选的方向恰好相反，因此即使部分普通组合指标可接受，也不能晋级。

## 数据与方法可审计，失败不是数据故障

- 信号面板554,400行、5,775股、96个月；重复键0、未来信息违规0。
- Downside Beta 使用截至信号日的历史日收益和全A等权市场下跌日，要求至少120个总观测和30个下跌观测。
- 原始信号依次保留 raw、1%/99% winsorized、standardized 和经12项风险控制后的 neutralized 版本。
- 候选组合固定为80% 24月滚动回归基线加20%防御分数，没有搜索窗口、方向或权重。

## 风险中性化后没有独立防御信息

固定验证期 Downside Beta 与普通 Beta 的月度截面 Spearman 中位数为0.811。普通 Beta 已属于强制控制项；剥离后信号的 Partial IC 为-0.0085。多重检验中，下跌月相对基线收益变化均值为-0.142%，HAC `t=-5.023`、双侧 `p=0.00000051`，bootstrap 95%区间[-0.201%, -0.086%]。显著性确认的是不利方向，不能翻号解释为有效。

## 决定与后续边界

正式决定：`REJECTED`。当前 Downside Beta 构造停止，不得继续搜索同义窗口、方向或20%权重。Lane B 的“首轮研究 loop”已经完成，但“形成防御引擎”的目标尚未实现；如继续，只能选择 GOAL 列出的下一个独立机制家族并重新用 leader 对齐。

复算命令：

```powershell
$env:PYTHONPATH='src'
python -m scripts.v6.run_downside_beta_v6
```

机器结果：`artifacts/evaluations/downside_beta_v6_evaluation.json`；原始十段式报告：`artifacts/evaluations/downside_beta_v6_report.md`。
