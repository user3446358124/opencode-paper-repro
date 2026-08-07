---
description: 从系统 issue 或用户提出的系统功能要求启动受控 OpenCode 自我迭代
agent: system-maintainer
---
处理参数：`$ARGUMENTS`

若参数是 `SYS-...`，将它作为本地系统 issue ID；否则将其作为用户对 paper-repro 系统的改进要求。按照 system-maintainer 的隔离修改、测试、差异审查和受控应用流程执行。

不得把当前论文项目的依赖、数据、训练或算法问题当作 paper-repro 自我迭代任务。
