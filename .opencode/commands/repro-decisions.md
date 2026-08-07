---
description: 查看或调整复现过程中的自适应人工决策策略
agent: repro-orchestrator
---
参数：`$ARGUMENTS`

先调用 `repro_decision(action="policy-show")`。

支持意图：
- 无参数：显示当前模式、交互预算和待确认决策。
- `autonomous`：高自动化，仅高风险/不可逆/许可类决策必须询问。
- `balanced`：默认平衡模式；低风险自动，中高影响询问并尽量合并。
- `collaborative`：更多让用户参与，但仍遵守交互预算。
- `strict`：谨慎模式，所有有实质影响的选择都要求确认。
- `pending`：调用 `repro_decision(action="list-pending")`。
- `checkpoint`：调用 `repro_decision(action="checkpoint")`，将相关待决策项合并成一次中文询问。

若用户要改变模式，调用 `repro_decision(action="policy-set", mode="<MODE>", scope="workspace")`。说明 `--auto` 只控制 OpenCode 工具权限，不会绕过本系统的语义决策检查点。
