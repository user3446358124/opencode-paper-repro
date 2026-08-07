---
description: 查看 paper-repro 系统自我迭代队列、策略和待验证提案
agent: repro-orchestrator
---
先调用 `repro_self(action="policy-show")`，再调用 `repro_self(action="list")`。

用中文按状态汇总：排队、隔离修改中、测试失败、已生成提案、等待决策、已应用待真实验证、已验证、已丢弃或已回滚。不得混入项目 blocker。
