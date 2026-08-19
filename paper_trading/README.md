# 模拟仓 v2（25% 红利 + 75% 波动趋势，Top50）

本地、只读市场数据的模拟交易与 P2 影子验证系统。固定安全开关为 `TRADING_MODE=paper`、`ALLOW_LIVE_TRADING=false`、`ENABLE_ORDER_SUBMISSION=false`；代码中没有券商下单适配器。

## 执行口径

- 当前策略为历史税后回看最优的 Top50：25% 红利分仓 + 75% 波动趋势分仓。红利和波动组股票成分均按月更新；波动组组合层目标仓位按 60 日波动率和 250 日趋势每日复算，变化达到 1% 才交易。
- 扫描每天运行并展示候选变化；非月末的成分变化只作为观察名单，不是拟买卖指令。执行端读取交易所开市日历，仅在月度成分触发或日频仓位阈值触发后生成下一交易日计划。
- 收盘后产生目标计划，下一交易日开盘撮合，不允许同收盘价成交。
- A 股 100 股整手；佣金万 1.2、单笔最低 5 元；卖出印花税在 2023-08-28 前为千 1、之后为万 5。
- 现金分红在股权登记日确认权利、派息日入账；卖出时按 FIFO 结算红利税。持有期按自然月/自然年计算：1 个月以内 20%，超过 1 个月至 1 年 10%，超过 1 年免税。
- 月末成分调仓按交易所日历判断；缺失开盘价时保留原持仓与待执行计划，不以零价删除。
- 标的至少上市 180 天、20 日平均成交额不低于 100 万元，排除 ST/退市及北交所标的。
- 组合达到硬回撤线时，明确动作是将波动率分仓目标降至现金；风险控制不会被绕过。

一年持有保护的对照实验显著损害收益和回撤，因此没有上线硬保护；生产模拟仓保留真实 FIFO lot 与递延红利税核算。详见 `TAX_LOT_VALIDATION.md`。

## 首次升级

旧版 `state.json` 中的持仓没有真实成交成本和 lot 记录。v2 会保留它作为诊断证据并标记 `legacy_import=true`，同时硬阻断后续执行。先备份旧文件，再从前端点击“重置 v2 模拟仓”或调用 `/api/reset`。原先两个交易日的数据不能当作 v2 的有效影子验证样本。

## 每日操作

在仓库根目录执行：

```powershell
python -m paper_trading.app
```

打开 `http://127.0.0.1:8000`，按页面编号操作：

1. 更新市场数据。
2. 每日扫描两分仓：复核月度成分触发、非执行观察名单和波动组日频仓位阈值。
3. 执行当日盘后结算、收盘估值和下一开盘计划。
4. 独立运行 P2 健康检查。
5. 录入外部模拟仓现金/持仓快照并对账。

P2 不改变策略或交易管线，只累计运行完整性、对账覆盖率/通过率、月末周期和告警。验收门槛为至少 60 个影子日、3 次月末、对账覆盖率不低于 95%、通过率不低于 99%。

## 验证

```powershell
python -m pytest -q tests/paper_trading
python -m paper_trading.p1_validation --data-root <research-data-path>
python -m paper_trading.frequency_validation --data-root <research-data-path> --dividend-history paper_trading/data/dividend_history_tushare.parquet
```

P1 的结果和限制见 `P1_VALIDATION.md` 与 `p1_results.json`；红利税和持有约束实验见 `TAX_LOT_VALIDATION.md`；频率对照和选型见 `FREQUENCY_VALIDATION.md`。
