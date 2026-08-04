# fixed_weight_allocator_v6 事前登记

- `registration_date`: 2026-08-03；输入审计前登记
- `lane`: Lane G 总组合配置器
- `method`: 固定权重；60%指数增强、20%横截面防御、20%独立Alpha。
- `eligible_decisions`: `PROMOTE`、`PROMOTE_TO_LIVE_SHADOW`、`SHADOW`，以及GOAL明确冻结的当前24月滚动回归 `SHADOW_BASELINE`。
- `required_roles`: `index_enhancement`、`defensive`、`independent_alpha` 各至少1个。
- `forbidden_inputs`: `REJECTED`、`DATA_BLOCKED`、仅有基础设施无独立验证、无月收益/持仓/成本容量证据的候选。
- `missing_role_protocol`: 状态`DATA_BLOCKED`；不以现金、零收益或拒绝候选填补；不计算总组合收益。
- `validation`: 若角色齐全才在2023-07-01至2026-06-30运行；权重不搜索。
- `maximum_variants`: 1。
