你是执行者，这份任务书是唯一任务来源；中途没人可问，拿不准的写进 `development/16-alpha-factor-phase1/BLOCKED_V7.md`，跳过后继续不受影响项。
断线或换会话先读 `CONTEXT_HANDOFF_V7.md`、`PROGRESS_V7.md` 和本书，完成一项立刻更新进度，禁止重做。
这项工作建立V7最小公共协议，使后续每个research_id都无法绕过角色分级、Stage S/P门禁和历史/实时证据边界。
冲突时：证据真实性 > 死亡边界 > fail-closed门禁 > 功能完整 > 速度。
“只允许/不许”是硬约束；“建议”可调整，但须在PROGRESS记录理由。

## 我替领导拍的板

- 公共协议不占三个正式research_id（猜的）｜若算正式预算会挤掉C7。
- 只实现当前V7明确要求的schema和门禁，不造通用回测框架（猜的）｜避免先平台后研究。
- 复用V6统计/影子函数，只有V7差异放入新目录（猜的）｜代价是保留少量跨版本依赖。

## 界限

只允许新增/修改：`src/quant_trading_system/research/v7/**`、`scripts/v7/**`、`tests/research/v7/**`、`development/16-alpha-factor-phase1/{PROGRESS_V7.md,BLOCKED_V7.md}`。其余只读。不得改GOAL_V7、V6代码/测试、旧评价产物、既有账本、归档和pytest配置。不得安装依赖、改生产库或写实时影子。

## 现状与任务0

2026-08-03实测：上述三个V7代码目录均不存在；V6测试77 passed；GOAL_V7 SHA256为 `88AABA...164CC4E`。先运行：

`python -m pytest tests/research/v6 -q`

必须得到77 passed；再核对三个V7目录不存在或仅含本任务新文件。对不上即把证据写入BLOCKED最上方，只做不受影响项。核对后在PROGRESS用不超过10行写目标、顺序、最大风险。

## 任务1：登记和角色门禁

实现最小V7 registration校验：唯一research_id、`post_v6_hypothesis=true`、唯一核心期限/主基准、角色、变体数、历史证据用途、实时最低长度、放宽项及逐项补偿控制。角色只允许GOAL列出的七类；缺字段、未知角色、禁止放宽项或无补偿时必须抛错。验收：

`python -m pytest tests/research/v7 -q`

须覆盖合法登记及每类非法输入，0 skipped。

## 任务2：Stage S/P与决策状态机

Stage P只有Stage S为 `SIGNAL_VALID` 才可运行；历史诊断不得产生PROMOTE/SHADOW，实时样本未达登记长度也不得晋级；REJECTED不可恢复或进入组合。实现纯函数和小型测试，不运行策略。反向验证：临时构造“历史好结果直接PROMOTE”和“REJECTED进入G”，测试必须变红；恢复后全绿，并把红→绿摘要写PROGRESS。

## 规矩

禁止skip/todo、删测试、放宽断言、mock被测状态机、改GOAL/阈值、`|| true`。V6测试数不得下降。连续三次同一验收失败则停止该项，记录死因，转做不受影响项；结果比基线差就回滚自己的改动。

## 完成条件

1. V7测试覆盖登记、角色、Stage门禁、历史/实时边界和拒绝输入，全部通过且0 skipped；2. V6仍77 passed、GOAL_V7哈希不变，白名单外无改动。每条都在PROGRESS贴实际命令输出及反向验证红→绿；BLOCKED空也写“无”。或三轮验收已用尽，停止并如实交付差距。
