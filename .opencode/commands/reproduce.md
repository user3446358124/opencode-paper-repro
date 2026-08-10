---
description: 在当前项目中开始完整论文复现
agent: repro-orchestrator
---
在当前 OpenCode 工作区开始一次全新的论文复现。

参数：$ARGUMENTS

参数通常是：`<GitHub仓库地址或当前仓库> <论文PDF路径或URL>`。

可附加决策偏好，例如 `--decision-mode balanced`、`--decision-mode autonomous`、`--decision-mode collaborative` 或 `--decision-mode strict`。未指定时使用 workspace/global 的当前策略，默认是 `balanced`。

若参数中包含 `--decision-mode <MODE>`，在创建 run 前调用 `repro_decision(action="policy-set", mode="<MODE>", scope="workspace")`，并从传给仓库/PDF 的实际参数中去掉该标志。

必须首先调用 `repro_start`，再调用 `repro_environment(action="show")` 和 `repro_decision(action="policy-show")`。运行状态写入当前工作区 `.paper-repro/`。按固定 8 步调用 `repro_stage`，每次携带 step、step_total=8、step_name 和 step_status。不得把当前文件夹名自动当成 Conda 环境名。

进入第 6 步 execution 前必须调用 `repro_runtime(action="gpu-prepare")`。若本次 run 尚未确认 GPU 资源池，先向用户展示检测到的 GPU 编号、型号、显存占用和利用率，并询问本次允许调度哪些 GPU；得到明确选择后再 `repro_runtime(action="gpu-configure", gpu_ids=[...])`。之后由 experiment-runner 根据 reproduction_matrix 生成完整任务图，优先一次 `plan-submit`。长任务由持久调度器执行，OpenCode 不同步等待任务结束。
