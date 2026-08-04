# Lane G 总组合报告：输入资格不足，固定权重配置被阻断

## 技术摘要

Lane G 已完成正式输入资格审计，状态为 `DATA_BLOCKED`。七个候选输入中只有冻结的24月滚动回归当前影子基线具备准入资格，角色为 `index_enhancement`；`defensive` 和 `independent_alpha` 两个必需角色均为0。根据 GOAL“未经独立验证的历史候选不得进入正式配置”的硬约束，没有计算60/20/20总组合收益，也没有用现金、零收益或被拒候选填补缺口。

## 机器审计只识别出一个合格角色

| 输入 | Lane/角色 | 决策 | Lane G资格 |
|---|---|---|---|
| 24月滚动回归冻结影子基线 | A / 指数增强 | `SHADOW_BASELINE` | ELIGIBLE |
| 收缩ICIR | A / 指数增强 | `REJECTED` | 禁止 |
| Downside Beta | B / 防御 | `REJECTED` | 禁止 |
| Quality-adjusted Value | C / 独立Alpha | `REJECTED` | 禁止 |
| 连续跌停打开反转 | D / 独立Alpha | `REJECTED` | 禁止 |
| 行业残差动量 | E / 独立Alpha | `REJECTED` | 禁止 |
| 行业相对动量 | F / 独立Alpha | `REJECTED` | 禁止 |

机器结果：`eligible_count=1`，可用角色只有`index_enhancement`，缺失`defensive`和`independent_alpha`。

## 固定配置方法已经登记，但没有获得运行授权

首个配置方法事前冻结为：60%指数增强、20%横截面防御、20%独立Alpha。只有三类输入各至少一个且状态为PROMOTE/SHADOW时才允许计算固定验证组合。资格门禁通过反向测试：将`REJECTED`候选强行标作输入时审计会变红。

当前若强行运行，只会得到“一只指数增强基线加两个伪零序列”的退化结果，无法检验收益来源分散、相关性、交易净额或风险预算。因此不生成收益曲线是正确的研究结果。

## 决定、限制与解锁条件

正式决定：`DATA_BLOCKED`，`portfolio_computed=false`。这不是数据文件缺失，而是上游独立验证资格缺失。Lane G 的本轮研究已经到达合规终点；解锁必须来自未来新的、事前登记并通过固定验证或进入实时影子的防御引擎和独立Alpha引擎。不得修改A–F既有决策或把多个拒绝构造拼接成“分散”。

复算命令（预期非零退出并写入审计）：

```powershell
$env:PYTHONPATH='src'
python -m scripts.v6.audit_lane_g_inputs_v6
```

机器结果：`artifacts/evaluations/fixed_weight_allocator_v6_input_audit.json`。
