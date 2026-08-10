---
description: 查看持久执行队列、调度器、任务进度、ETA 与 GPU 任务归属
agent: repro-orchestrator
---
调用 `repro_runtime(action="status")`。用中文汇报：调度器状态、总任务/运行中/等待/完成/失败数量；每个任务的 task_id、名称、GPU、真实进度来源、ETA；本次允许调度的 GPU 资源池；哪些 GPU 被 paper-repro 任务占用、哪些疑似被外部任务占用。不要从其他日志或 PID 反推任务归属。
