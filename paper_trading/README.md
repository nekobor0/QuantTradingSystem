# 模拟仓 v3：A/B 双策略与独立 P2 影子验证

本地、只读市场数据的纸面交易系统。A、B 是两个相互独立的备选策略，各自以 100 万元起始，不合并为 200 万元组合：

- A：25% 红利分仓 + 75% 波动分仓（历史税后综合表现较优的主方案）。
- B：75% 红利分仓 + 25% 波动分仓（同规则的对照方案）。

固定安全开关为 `TRADING_MODE=paper`、`ALLOW_LIVE_TRADING=false`、`ENABLE_ORDER_SUBMISSION=false`；代码中没有券商下单适配器。

## 执行口径

- A/B 共用同一套候选筛选和交易规则，但资金、现金、整手取整、最低佣金、FIFO lot、税费、计划和成交记录完全独立。
- 每日扫描 A/B 四个分仓。红利和波动组的股票成分按月更新；波动分仓的组合层目标仓位按 60 日波动率和 250 日趋势每日复算，变化达到 1% 才交易。
- 非月末成分变化只作为观察名单，不是拟买卖指令。执行端读取交易所开市日历，仅在月度成分触发或波动仓日频仓位阈值触发后生成下一交易日计划。
- 收盘后产生目标计划，下一交易日开盘撮合，不允许同收盘价成交。
- A 股按 100 股整手交易；佣金万 1.2、单笔最低 5 元；卖出印花税在 2023-08-28 前为千 1、之后为万 5。
- 现金分红在股权登记日确认权利、派息日入账；卖出时按 FIFO 结算红利税。持有期按自然月/自然年计算：1 个月以内 20%，超过 1 个月至 1 年 10%，超过 1 年免税。
- 月末成分调仓按交易所日历判断；缺失开盘价时保留原持仓与待执行计划，不以零价删除。
- 标的至少上市 180 天、20 日平均成交额不低于 100 万元，排除 ST/退市及北交所标的。
- 任一策略达到硬回撤线时，仅把该策略的波动分仓目标降至现金；不会连带改变另一个策略。

一年持有保护的对照实验显著损害收益和回撤，因此没有上线硬保护；生产模拟仓保留真实 FIFO lot 与递延红利税核算。详见 `TAX_LOT_VALIDATION.md`。

## 从旧账本升级

v3 状态包含 A/B 两套独立账本。v1/v2 只能保留为诊断证据：旧持仓迁入 A，B 建立空白账本，并标记 `legacy_import=true`，后续执行会被硬阻断。应先备份旧文件，再用确定性回放重建：

```powershell
python -m paper_trading.replay_shadow --start 2026-08-17 --end 2026-08-19 --state-file paper_trading/data/state.json --confirm-reset
```

## 每日操作

在仓库根目录执行：

```powershell
python -m paper_trading.app
```

打开 `http://127.0.0.1:8000`，按页面编号操作：

1. 更新市场数据，并检查有效交易日与各数据集新增条数。
2. 扫描 A/B 四分仓信号，区分月末拟买卖与非执行观察名单。
3. 同时完成 A/B 的当日盘后结算、收盘估值和下一交易日开盘计划。
4. 独立运行 P2 健康检查，覆盖 A/B 两套账本。
5. 录入 A/B 四分仓的外部现金和持仓快照并对账。

页面以同一账本 NAV 同时驱动净值表和 A/B 累计收益曲线，避免表格与图表口径漂移。

P2 不改变策略或交易管线，只累计运行完整性、四分仓外部快照对账覆盖率/通过率、月末周期和告警。验收门槛为至少 60 个影子交易日、3 次月末、对账覆盖率不低于 95%、通过率不低于 99%。

## 验证

```powershell
python -m pytest -q tests/paper_trading
python -m paper_trading.p1_validation --data-root <research-data-path>
python -m paper_trading.frequency_validation --data-root <research-data-path> --dividend-history paper_trading/data/dividend_history_tushare.parquet
```

P1 的结果和限制见 `P1_VALIDATION.md` 与 `p1_results.json`；红利税和持有约束实验见 `TAX_LOT_VALIDATION.md`；频率对照和选型见 `FREQUENCY_VALIDATION.md`。
