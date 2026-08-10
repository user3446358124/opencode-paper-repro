---
description: 检查并配置本次复现允许自动调度的 GPU
agent: repro-orchestrator
---
先调用 `repro_runtime(action="gpu-prepare")`。如果本次 run 尚未确认 GPU 资源池，把检测到的 GPU 编号、型号、显存占用、利用率用中文展示，并询问用户“本次允许调度哪些 GPU？”。建议答案为 `0,1` / `0` / `1` / `none` 这样的物理 GPU 编号集合。收到用户明确选择后调用 `repro_runtime(action="gpu-configure", gpu_ids=[...])`；除非用户要求，否则不要启用 allow_external_busy。
