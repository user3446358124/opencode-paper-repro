# v2.0.0 → v2.1.0 覆盖升级说明

v2.1.0 不改变 v2.0 的 Task Registry/Scheduler/GPU 调度核心，主要稳定 Remote Bridge 契约。

## 升级

完全退出 OpenCode。当前 Scheduler 中仍有任务时，先等待任务完成或显式停止，避免替换正在使用的控制代码。

```bash
conda activate <paper-repro-control>
cd /path/to/opencode-paper-repro-starter-v2.1.0
PAPER_REPRO_SKIP_DEPENDENCIES=1 bash bootstrap.sh
hash -r
```

检查：

```bash
paper-repro --version
paper-repro remote capabilities --json
paper-repro remote discover --active --json
```

版本应为 `2.1.0`。

## Remote Bridge 必须调整的一点

事件 cursor 从 v2.1 起明确规定为 run-scoped。Bridge 请保存：

```text
workspace_id + run_id + event_id
```

`run_id` 变化或 `cursor_found=false` 时重置 cursor。

## 保留兼容性

- v2.0 的 Task Registry、GPU policy、execution plan 不需迁移；
- snapshot 保留 `task_list` 和精简 `gpu` 兼容别名，但新 Bridge 应使用新的 `tasks.active/queued/recent_completed` 与 `gpu_assignments`；
- 统一密钥、模型路由、MCP、决策偏好、历史 run 均保留。
