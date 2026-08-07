---
description: 安全地把 paper-repro 系统源码发布到用户自己的 GitHub 仓库；先配置、隐私扫描和人工确认
agent: open-source-publisher
---
执行 paper-repro 开源发布流程。参数：`$ARGUMENTS`。

先调用 `repro_publish(action="policy-show")`。若 GitHub owner、repository、visibility、license 或认证方式缺失，用一次合并询问向用户收集；禁止要求用户在聊天中粘贴 Token。

如果参数是：
- `status`：调用 policy-show、auth-status 和 list，只报告状态。
- `prepare [IMPROVEMENT_ID]`：准备隔离系统源码快照并执行隐私扫描。
- `review <PUBLICATION_ID>`：展示扫描结论、文件数量、警告和下一步。
- `publish <PUBLICATION_ID>`：先通过决策层和精确确认短语获得用户批准，再调用 push。
- 空参数：引导完成配置、认证、准备、扫描、审查和最终发布。

任何扫描阻断、认证异常或 GitHub push protection 阻断都必须停止。不得上传当前论文项目或运行数据。
