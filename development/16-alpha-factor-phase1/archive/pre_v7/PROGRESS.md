# 阶段一续跑记录

更新时间：2026-07-29（Asia/Shanghai）

## 开工回执

- 目标：严检至少 10 个有可证伪逻辑的 A 股 Alpha 因子，争取筛出至少 5 个低相关入库因子。
- 顺序：生产库与旧资产审计 → 补复权/行业/指数历史 → 固化研究协议 → 批量检验 → 入库与报告。
- 最大风险：当前生产库的复权因子、行业、指数历史成分均为空，且当前证券清单可能有幸存者偏差。
- 守则：不因目标数量修改门槛；样本外只评一次；所有失败保留证据。

## 已完成

- 已读取 `leader` Skill、结构规范和风格规范，并建立本任务书。
- 已确认 Docker PostgreSQL healthy，仅绑定 `127.0.0.1:5432`。
- 已用只读 SQL 实测：7,145 个 instruments；5,533 个 A_SHARE；16,342,981 条 1d bars；7,133 个有日线的证券；覆盖 2005-01-04 至 2026-07-28。
- 已实测：`adjustment_factors=0`、`classification_memberships=0`、`universe_memberships=0`。
- 已确认 `docs/integrations/tdx-bridge.md`：入库 OHLC 是未复权，`ForwardFactor` 仅保存在 raw JSON，尚未发布。
- 已确认 `.venv` 有 pandas/pyarrow/numpy，无 scipy/statsmodels；优先用 numpy 实现必要统计，避免无理由加依赖。
- 已确认 8,852 个 TDX raw JSON 的日线字段包含等长 `ForwardFactor` 和 `VolInStock`；抽样 `ForwardFactor` 符合最新日归一为 1 的前复权乘数形态。
- 已检查 MvpSelect 复权资产：归档因子仅 842 行/83 只证券，扩展日线大量 `adj_factor=1.0`，不能直接作为全市场逐日因子。
- 已探测现有 Tushare：`index_weight` 和 `index_classify` 均被明确拒绝权限，`stock_basic` 返回 0 行。
- 已检查 AkShare 本机指数成分接口签名：仅最新截面，无历史日期参数。
- 已形成 `DATA_AUDIT.md`，记录数据缺口、可恢复字段和所需补充。
- 已新增严格 TDX raw 解析器与审计器；7 个研究测试通过、mypy 3 个源文件无问题，破坏字段长度/因子/日期/股本会明确失败。
- 已全量扫描 8,845 个 raw JSON：选中 5,533 只 A 股、14,916,622 行，清单覆盖率 99.84%，复权因子覆盖 100%，所有证券最后因子为 1。
- 全量审计推翻了抽样假设：`VolInStock` 14,916,622 行全部为 0，不能构造流通市值。
- 已定位 MvpSelect 历史总市值候选：4,274,526 行、5,428 只、无空值/重复键；最近 36 个月每月覆盖至少 5,039 只。
- 环境事实：项目 `.venv` 未安装 pytest/mypy，研究验收需用系统 Python；`.venv` 可运行项目脚本及 pandas/pyarrow。

## 正在做

- 子任务 1 局部完成、整体暂停：复权因子与规模候选已审计；等待历史行业成员与沪深300/中证500历史成分的数据权限或文件。

## 下一步

1. 收到补充数据后验证 schema、时间区间、重复键和 point-in-time 语义。
2. 从 TDX raw 物化逐日复权因子；用 AkShare 历史总市值构建规模暴露并做交叉抽查。
3. 汇总 A_SHARE 日线逐年/逐证券覆盖，随后进入 10 个候选因子的固定协议。

## 续跑入口

新任务先读 `GOAL.md`、本文件、`BLOCKED.md` 和 `DATA_AUDIT.md`；从 `BLOCKED.md` 的“需要用户配合”开始，不要重做已完成的数据库与接口探测。
