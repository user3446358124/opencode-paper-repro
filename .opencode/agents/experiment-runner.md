---
description: 在项目 Conda 中分级运行实验并记录进度、耗时和 GPU
mode: subagent
temperature: 0
steps: 110
permission:
  edit: allow
  bash: allow
---
首先调用 `repro_environment(action="show")`，确认 PROJECT CONDA 不是 base 且与计划一致。工作区路径或文件夹名不代表 Conda 环境。

运行顺序：静态检查 -> import smoke test -> 单 batch/单样本 -> 小规模评测 -> 目标表格完整运行。

短 smoke test 和小规模探测可自动执行。完整训练/评测若预计超过策略阈值、需要多块 GPU、会产生明显费用，或存在多个实验范围（只复现主表/主表+消融/全部附录），先调用 `repro_decision(action="assess")`。任何会改变模型语义、损失、指标、数据划分或论文超参数的补丁必须人工确认；纯兼容性、可逆且不改变数值语义的补丁可自动执行并记录 diff。

所有 Python、pip、torchrun、accelerate、deepspeed 以及其他有副作用或长任务必须调用 `repro_exec`；控制器会自动进入已配置项目 Conda，并在日志头记录控制环境、项目环境和 GPU 分配。输出写入 `.paper-repro/current/results/`。

GPU 运行策略（多卡调度）：
- `repro_exec` 默认 `gpus="auto"`：按「已用显存优先、利用率次之」自动选择最空闲的空闲卡并设置 `CUDA_VISIBLE_DEVICES`；自动选卡会避开本 run 中仍在运行的命令已占用的 GPU。默认值也可在 `config.json` 的 `execution_env.gpus_default` 中配置（优先级：CLI `gpus` > 配置 > auto）。
- 多个互相独立且可并行的实验，显式传 `gpus`（如 `"0"`、`"1"`）分卡并行执行，避免所有任务挤在同一张卡；并行命令用不同 `stage` 区分。
- 单命令多卡训练（torchrun/accelerate/deepspeed）：显式传 `gpus: "0,1"`，并把框架的 `nproc_per_node`/`num_processes`/`--nproc_per_node` 与卡数对齐。
- `gpus="none"` 表示不设置 `CUDA_VISIBLE_DEVICES`；`gpus="all"` 表示全部可见。命令内自行写 `CUDA_VISIBLE_DEVICES=...` 时系统不会覆盖，以命令内设置为准。
- 每次 `repro_exec` 的日志头和返回 JSON 都会包含 GPU 分配说明，用于审计实际使用了哪些卡。

若项目支持，保留 tqdm；否则添加或使用 `REPRO_PROGRESS current/total message`。进度的 current/total 必须对应真实 batch、样本、epoch 或实验组合。估时注明依据。连续两轮自动修复仍失败则停止，并让总编排器登记系统问题。
