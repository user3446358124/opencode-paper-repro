---
description: 从当前项目最近检查点继续复现
agent: repro-orchestrator
---
读取当前工作区 `.paper-repro/current` 指向的 run，并检查 `meta/state.json`、`execution/commands.jsonl`、`assets/artifacts.jsonl` 与 `report/RUN_BLOCKERS.md`。从第一个未完成阶段继续；先验证已有产物哈希，不重复下载或覆盖成功结果。
