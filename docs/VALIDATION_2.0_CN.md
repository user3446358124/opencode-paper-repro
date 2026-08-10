# v2.0.0 执行内核验证记录

验证日期：2026-08-10

## 静态验证

- `scripts/reproctl.py` Python 编译通过。
- `scripts/runtime_engine.py` Python 编译通过。
- `bootstrap.sh` Shell 语法通过。
- 新增 JSON Schema 均可解析。
- `opencode.jsonc` 权限模板包含长任务 bash deny 规则。

## Runtime 功能验证

使用模拟双 GPU 遥测与隔离临时 workspace 验证：

- 未确认 GPU pool 时 GPU task 保持 `waiting-resources`。
- 确认 GPU0/GPU1 后任务可启动。
- 两个独立单卡任务可分别分配 GPU0/GPU1 并行运行。
- 先完成的 GPU 会自动领取后续队列任务，无需 Agent 唤醒。
- 显式双 GPU 任务能够一次分配 `[0,1]`，并保留 parallel_group。
- 外部负载超过阈值时，调度器不会抢占该 GPU；资源恢复后自动继续。
- 标准 tqdm 行可解析 current/total/percent/ETA/source。
- `REPRO_PROGRESS` 仍为最高优先级原生进度协议。
- `remote snapshot` 默认删除 command/cwd/Conda prefix。
- `remote events` 使用稳定递增 event ID。
- `remote discover` 可在不知道项目目录时发现已注册 run。

## 已知边界

- 不同论文仓库的实际 VRAM 需求仍需 Agent 从 README/配置/历史运行估计；调度器不会凭模型名称猜显存。
- 一个 task 是否应该使用 DDP、data parallel 或多个独立单卡任务，仍属于 execution plan 语义，由论文代码入口决定。
- `nvidia-smi` 只用于资源可用性和原始遥测；容器内看不到宿主 PID 不影响 task ownership，因为 ownership 来自 Task Registry。
