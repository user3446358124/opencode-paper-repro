---
description: 对齐论文内容与代码能力，判定可复现范围
mode: subagent
temperature: 0
steps: 40
permission:
  edit: allow
  bash: deny
---
比较 `.paper-repro/current/analysis/paper_manifest.json` 与 `repo_manifest.json`，输出 `.paper-repro/current/analysis/reproduction_matrix.json`。

粒度必须到表格单元、行或列。字段包括 paper_item、table、row、column、metric、paper_value、code_entrypoint、config、required_assets、expected_output、status、confidence、evidence、blockers。

status 只能是 exact、partial、not_implemented、blocked、ambiguous。只有入口、数据、指标实现、配置和输出字段都能对应时才可标 exact。
