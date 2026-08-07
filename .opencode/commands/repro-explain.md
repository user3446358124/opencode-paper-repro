---
description: 生成整篇代码、调用链和论文核心实现的中文阅读手册
agent: code-explainer
---
讲解当前工作区代码。参数：`$ARGUMENTS`

默认参数为 `all`。也可使用：
- `/repro-explain overview`
- `/repro-explain call-chain`
- `/repro-explain paper-core`
- `/repro-explain data-flow`
- `/repro-explain runtime`
- `/repro-explain module <模块名>`
- `/repro-explain file <相对路径>`

开始时调用 `repro_code(action="index")`。优先复用当前 run 已生成的论文/代码审计和运行日志；若尚无 run，也可先生成静态代码讲解，并明确哪些内容缺少论文或运行证据。
