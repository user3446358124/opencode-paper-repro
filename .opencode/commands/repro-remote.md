---
description: 输出供 Remote Bridge / WorkBuddy 使用的稳定机器可读运行快照
agent: repro-orchestrator
---
先调用 `repro_runtime(action="remote-capabilities")`，再调用 `repro_runtime(action="remote-snapshot")`。

Remote Contract v1 已冻结。远程系统应优先消费 `paper-repro remote capabilities --json`、`remote discover --active --json`、`remote snapshot --json` 和增量 `remote events --after <EVENT_ID> --json`。事件 cursor 是 **run-scoped**，必须保存 `(workspace_id, run_id, event_id)`；新 run 或 `cursor_found=false` 时重置 cursor。consumer 必须忽略未知新增字段，不能通过 paper-repro 版本字符串猜 capability。

默认快照不包含完整 task command、cwd、Conda prefix 或任何 secret。工作区路径会保留用于 OpenCode session directory 匹配；如果 Bridge 会把状态继续发送到不受信任的外部服务，应在 Bridge 展示/转发层自行脱敏。

OpenCode permission/question/prompt/slash command 不由 paper-repro 代理，Bridge 直接使用当前 OpenCode Server 的公开 HTTP/OpenAPI 能力；paper-repro 只维护研究决策、task/GPU/progress/ETA 语义和可选 session hint / command audit 元数据。
