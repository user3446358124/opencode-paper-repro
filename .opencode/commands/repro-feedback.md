---
description: 生成聚焦系统功能的脱敏反馈包
agent: repro-orchestrator
---
调用 `repro_feedback` 生成反馈包。默认只包含 paper-repro/OpenCode 集成自身的功能问题、诊断和优化建议，不包含某个论文项目的依赖、数据、训练或评测阻塞。只有用户明确要求时才包含截断和脱敏后的最近日志。返回反馈包路径和包含内容。
