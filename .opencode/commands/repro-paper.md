---
description: 检查 PDF 文本层、视觉页和当前论文审计策略
agent: paper-auditor
---
参数：`$ARGUMENTS`

先调用 `repro_paper(action="policy-show")`。若参数包含 PDF 路径，则调用 `repro_paper(action="inspect", input="<PDF>")`，用中文说明：
- 哪些页有可靠文本层；
- 哪些页应调用视觉模型；
- 当前是 targeted / on-demand / all-pages / off 哪种策略；
- 文本层和视觉层各自负责什么；
- 后续 paper_manifest.json 如何记录真实调用来源。
