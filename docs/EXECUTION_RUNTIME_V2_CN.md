# paper-repro v2.0 执行内核与 GPU 调度说明

## 1. 为什么需要重构

v1.x 的执行阶段虽然已有 `repro_exec`、GPU 采样和状态页，但仍有四个结构性问题：

1. OpenCode 工具调用层会等待长任务返回，主 Agent 会话可能长时间 busy；如果绕过 `repro_exec` 用 bash/setsid/nohup，风险更高。
2. GPU 与“哪个论文任务”之间没有稳定的任务注册表，外部监控只能从 PID、命令行和日志反推。
3. 多卡场景中，Agent 需要持续在线才能在一项实验结束后启动下一项，GPU 容易空转；默认也容易串行执行。
4. 进度和 ETA 与具体任务没有强绑定，tqdm、JSONL 输出和日志可能被错配。

v2.0 将 execution 从“Agent 执行命令”改成“Agent 生成计划，持久调度器执行计划”。

## 2. 新职责边界

```text
OpenCode / experiment-runner
  负责：理解论文、代码、配置，生成 execution plan
        │
        ▼
paper-repro Scheduler
  负责：任务队列、依赖、GPU 分配、并行、自动补位、进度、ETA
        │
        ├─ Task Worker A -> GPU0
        ├─ Task Worker B -> GPU1
        └─ Task Worker C -> 等待 GPU，B 完成后自动补位

Remote Bridge / Web / 手机
  负责：读取 remote JSON、展示、回传结构化决策
```

OpenCode 主会话不再是长任务生命周期的宿主。

## 3. 每次 run 必须确认 GPU 资源池

执行阶段开始前：

```bash
paper-repro gpu prepare --json
```

会返回：

- 物理 GPU ID；
- 型号；
- 总显存/已用显存/空闲显存；
- 利用率、温度、功耗；
- 以前保存的 workspace 建议；
- 本次是否已经确认；
- 建议选择。

OpenCode 会把这些信息展示给用户，询问：

> 本次复现允许 paper-repro 调度哪些 GPU？

用户例如选择 GPU0、GPU1：

```bash
paper-repro gpu configure --ids 0,1 --max-parallel 2
```

CPU-only：

```bash
paper-repro gpu configure --ids none
```

可记住为下一次 run 的**建议**：

```bash
paper-repro gpu configure --ids 0,1 --max-parallel 2 --remember-workspace
```

即使记住，每次新 run 仍默认重新确认，避免服务器用途变化后误占其他任务的 GPU。

### GPU pool 是硬边界

如果本次只批准 `[0,1]`：

- 调度器永远不会使用 GPU2；
- execution plan 中指定的 task GPU affinity 不能扩展到池外；
- 未选 GPU 不属于本次复现资源；
- 默认情况下检测到外部负载的 GPU 会暂时跳过。

## 4. Execution Plan

在 GPU 范围确认后，`experiment-runner` 读取：

- `analysis/reproduction_matrix.json`；
- `analysis/repo_manifest.json`；
- README；
- 配置文件；
- 训练/评测入口；
- 需要复现的表格/行/列；

形成完整任务列表，而不是执行一个命令再想下一个。

示例：

```json
{
  "schema_version": 1,
  "tasks": [
    {
      "task_id": "eval-model-a-pope",
      "display_name": "Model-A / POPE",
      "command": "python -u scripts/eval_pope.py ...",
      "gpu_count": 1,
      "estimate_seconds": 7200,
      "progress_adapter": {"type": "tqdm"},
      "metadata": {"paper_targets": ["Table 2 / Model-A"]}
    },
    {
      "task_id": "eval-model-b-pope",
      "display_name": "Model-B / POPE",
      "command": "python -u scripts/eval_pope.py ...",
      "gpu_count": 1,
      "estimate_seconds": 7200,
      "progress_adapter": {"type": "tqdm"}
    }
  ]
}
```

提交：

```bash
paper-repro runtime plan submit --file execution-plan.json
```

OpenCode 中由 `repro_runtime(action="plan-submit", ...)` 完成。

## 5. 自动多卡调度

假设批准 GPU0、GPU1，并有 5 个相互独立的单卡任务：

```text
t=0
GPU0 -> task A
GPU1 -> task B
queue -> C D E

B 先完成
GPU1 -> task C（自动补位）

A 完成
GPU0 -> task D（自动补位）

...
```

无需 Agent 被“唤醒”才能接力。

### 多 GPU 单任务

任务需要两张 GPU：

```json
{
  "task_id": "train-ddp",
  "gpu_count": 2,
  "parallel_group_id": "ddp-main",
  "command": "torchrun --nproc_per_node=2 train.py ..."
}
```

调度器会一次性保留两张 GPU，并设置：

```text
CUDA_VISIBLE_DEVICES=<物理 GPU 列表>
REPRO_GPU_IDS=<物理 GPU 列表>
REPRO_GPU_COUNT=2
```

外部系统无需根据 PID/PPID 猜它是否是一个 DDP job。

## 6. Task Registry

每次 run 新增：

```text
.paper-repro/current/runtime/
├── tasks.json
├── task-specs.json
├── task-events.jsonl
├── remote-events.jsonl
├── snapshot.json
├── gpu-policy.json
├── execution-plan.json
├── scheduler.json
├── scheduler.pid
├── scheduler.log
└── worker-*.log
```

`tasks.json` 是任务语义快照，包括：

- task_id / display_name；
- stage / state；
- project env；
- gpu_request / gpu_ids；
- worker / launcher pid（仅诊断）；
- started_at / finished_at；
- progress / speed / ETA；
- progress source；
- log / output paths；
- dependencies / parallel_group；
- error / exit_code。

原始完整 command 单独放在权限更严格的 `task-specs.json`。远程安全快照默认不输出 command、cwd 和 Conda prefix。

## 7. repro_exec 在 v2.0 中的变化

过去：

```text
OpenCode -> repro_exec -> 等训练几个小时 -> Tool 返回
```

现在：

```text
OpenCode -> repro_exec -> 写入 Task Registry -> 返回 task_id
                                  │
                                  └-> 独立 Scheduler/Worker 继续运行
```

短时命令与长任务分开：

- `repro_cmd`：同步、受控、最长 30 分钟，用于环境探测、导入测试和短安装；
- `repro_exec`：异步持久任务，用于训练、评测、大型编译/下载和 GPU 工作负载。

因此 OpenCode 可以继续：

- 回答用户；
- 查看其他任务；
- 处理决策；
- 断开/重连；

而不会成为训练进程的生命周期依赖。

## 8. 进度适配器

优先级：

1. `REPRO_PROGRESS current/total message`；
2. 明确的输出 artifact 计数；
3. 当前任务自己的 tqdm；
4. 当前任务自己的 regex-log；
5. unknown。

支持：

```text
native
tqdm
jsonl-line-count
line-count
file-count
regex-log
auto
```

禁止扫描整个 `execution/logs/` 去找“最新 tqdm”，避免把任务 A 的进度认成任务 B。

### native

```text
REPRO_PROGRESS 309/500 evaluating sample 309
```

### tqdm

无需修改第三方项目时可使用：

```json
{"type":"tqdm"}
```

建议 Python 使用 `-u`，避免日志块缓冲。

### JSONL 结果计数

```json
{
  "type": "jsonl-line-count",
  "path": "results/predictions.jsonl",
  "total": 500,
  "unit": "sample"
}
```

## 9. ETA 语义

三种时间字段不能混用：

- `timeout_seconds`：硬超时上限；
- `estimate_seconds`：启动前粗估；
- `progress.eta_seconds`：运行后根据真实吞吐计算的剩余时间。

同时保存：

```json
{
  "eta_seconds": 3885,
  "eta_confidence": "high",
  "eta_source": "rolling-throughput",
  "estimated_finish_at": "..."
}
```

## 10. 状态命令

人类终端：

```bash
paper-repro status --watch
```

机器读取：

```bash
paper-repro runtime status --json
paper-repro runtime tasks --active --json
paper-repro runtime gpu --json
```

详情见 `REMOTE_RUNTIME_API_CN.md`。
