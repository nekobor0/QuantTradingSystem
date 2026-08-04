你是执行者，本文件是 features 模块唯一任务来源；换会话先读 `development/05-features/PROGRESS.md`。目标是把冻结的 universe/data snapshot 转成有定义、有版本、用途隔离、PIT 正确且可解释的特征集合。冲突按“无未来数据 > 输入/用途快照隔离 > 版本与血缘 > fail-closed > 覆盖率”处理。

## 冻结口径

- 首批生产公式固定：ETF_TIMING 使用 MOMENTUM、VOLATILITY、MAX_DRAWDOWN、LIQUIDITY；EQUITY_DAILY_SELECTION 使用 MOMENTUM、VOLATILITY、LIQUIDITY、EARNINGS_YIELD、ROE、GROWTH。只实现这些可审计公式，不做自动挖掘/调参。
- 所有输入统一为带 `observed_at/available_at/value/source_ref` 的 InputObservation；计算先验证 `available_at <= decision_at`、`observed_at <= as_of`、instrument 属于 universe snapshot。后复权价格只能由调用方提交 market_data snapshot 引用和 factor_version，不在本模块拼接。
- 版本固定 formula、参数、代码版本、依赖版本、最小历史、缺失策略。缺失策略只取 REJECT/KEEP_NULL；禁止无条件填 0。历史不足写质量标记但不缩小截面。
- 横截面处理只取 NONE/WINSOR_ZSCORE，边界与 ddof 固定在版本参数；截面成员就是 universe snapshot 成员。ETF 与个股用途、版本、snapshot 必须一致，交换即拒绝。
- 相同输入哈希幂等返回同一 feature_set；任何版本、参数、成员、data snapshot、factor_version 改变都生成新 ID/hash。未来追加数据不能改变历史输入哈希。
- IC/未来收益仅做 Diagnostic 独立存储，禁止进入 FeatureValue lineage。

## 地界与任务 0

- 只允许改 `src/quant_trading_system/features/**`、`migrations/005_features.sql`、`tests/features/**`、本文件、`development/05-features/**`。
- 01–04 模块及其测试/DDL、MvpSelect、模块规格、pyproject 只读；禁止联网、装依赖、容器。
- 开工指纹：05 文档 `08A6470EE7A95522566D166BCC7214BE638EB4814ED5C10E4DE5C8E469E5A85C`；索引/validator/pyproject 沿用已验指纹。上游 `282 passed`；features 0。
- 实测 MvpSelect factor_layer 有 15 个 Python 文件；calculator 与 registry 捕获异常继续，base 存在 `fillna(0)`，不满足 fail-closed/PIT，禁止直接搬运。
- 复跑基线和只读指纹；不一致写 BLOCKED 后只做无关工作。

## 任务 1：定义、公式与输入门禁

- 实现 FeatureDefinition/Version/InputObservation/FeatureValue/QualityFlag/Diagnostic；定义绑定唯一 purpose。
- 实现上述 6 类公式黄金样本：动量 `last/lag-1`；收益率样本波动；峰谷最大回撤；平均成交额流动性；盈利/市值；ROE 与同比成长直接取 PIT 财务输入。
- 窗口只含 as_of 及以前；历史不足、未来 observed/available、snapshot 外证券、混用途版本均显式拒绝或按版本 KEEP_NULL 标记。

## 任务 2：截面、集合与解释

- CalculateFeatureSet 输入显式 versions/as_of/decision_at/universe_snapshot/data_snapshot/input observations/factor_version；冻结固定行列，不静默丢行。
- WINSOR_ZSCORE 记录原值、截断边界、均值/标准差和处理值；零方差明确质量失败。ExplainFeatureValue 返回输入 source_ref、步骤和版本，不泄露未来。
- GetRequiredFeatureSet 从预注册 purpose binding 读取固定版本列表，不按当日 IC 选择。ETF/个股 FeatureSet ID 与哈希分域。

## 任务 3：存储与验收

- 内存/SQLAlchemy 双仓储与 `005_features.sql` 覆盖 definition/version/binding/set/value/input-lineage/quality/diagnostic/event 的唯一、外键、事务约束。
- features ≥75 passed、0 skipped；上游 282 项仍绿；compileall、mypy 五模块、文档校验均 0。
- 反向验证临时放宽 `available_at <= decision_at` 或用途隔离，既有测试必须非 0，恢复后全绿。

## 纪律与完成条件

- 禁止未来收益进入生产、异常后跳过、NULL→0、当日择优、mock 核心 PIT 门禁、删/skip/todo 测试、改白名单外文件或 `|| true`。测试数只增不减。
- PostgreSQL live 缺口如实记录。每项完成即更新 PROGRESS；全量验收最多 3 轮，首轮全绿即停并贴证据。

