---
description: 查看或配置当前项目使用的 Conda 执行环境
agent: repro-orchestrator
---
调用 `repro_environment(action="show")`，明确显示控制 Conda 与项目 Conda。若参数中给出环境名、prefix 或 Python 版本，则按用户意图调用 create 或 use。不得根据工作区文件夹名猜环境名，不得使用 base。
