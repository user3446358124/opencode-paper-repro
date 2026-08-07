---
description: 区分查看系统功能问题与项目复现阻塞项
agent: repro-orchestrator
---
读取：
- `.paper-repro/system/SYSTEM_ISSUES.md`：只汇总 paper-repro/OpenCode 集成能否正常运行、可观测性、安全性和优化空间。
- `.paper-repro/current/report/RUN_BLOCKERS.md`：当前论文项目的依赖、数据、模型、训练和评测阻塞。

分别汇总两类问题，不得把项目实现失败写入系统反馈。系统功能问题用 `repro_issue`；项目复现问题用 `repro_blocker`。

系统 issue 会按 `paper-repro improve policy show` 的策略进入自我迭代候选队列。若用户要求修复某一系统 issue，执行 `/repro-improve <SYS-ID>`；不得为项目 blocker 启动系统自改。
