---
description: 查看当前项目的中文复现步骤、环境、任务和 GPU 状态
agent: repro-orchestrator
---
调用 `repro_status`，使用中文汇报当前工作区、run ID、当前步骤 n/N、剩余步骤、控制 Conda、项目 Conda、持久调度器状态、任务队列总数/运行中/等待/成功/失败、每个任务的 GPU/进度来源/ETA、本次 GPU 资源池、GPU→task 归属、总耗时、系统功能问题数、项目复现阻塞项数、当前决策模式和待确认决策。任务语义只采用 paper-repro runtime registry；不要通过 PID 或其他任务日志猜测。不要启动新任务。
