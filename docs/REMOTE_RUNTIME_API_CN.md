# paper-repro v2.2 Remote Bridge Runtime Contract

## 1. 设计目标

paper-repro 是复现 `run / stage / task / GPU assignment / progress / ETA / blocker / research decision` 的业务事实源。

Remote Bridge 负责 SSH/MCP 传输、OpenCode HTTP、GPU 原始遥测、状态合并和远程交互。OpenCode permission/question/prompt/slash command 不由 paper-repro 代理。

推荐握手/读取链路：

```bash
paper-repro remote capabilities --json
paper-repro remote discover --active --json
paper-repro --workspace /srv/project remote snapshot --json
paper-repro --workspace /srv/project remote events --after EVT-... --json
paper-repro --workspace /srv/project remote decisions --json
paper-repro --workspace /srv/project remote decide DEC-... OPTION --json
```

## 2. capabilities：先做能力握手

```bash
paper-repro remote capabilities --json
```

示例：

```json
{
  "schema_version": 1,
  "contract": {
    "name": "paper-repro-remote",
    "major": 1,
    "minor": 0,
    "status": "frozen"
  },
  "paper_repro_version": "2.2.0",
  "capabilities": {
    "snapshot": 1,
    "events": 1,
    "decisions": 1,
    "task_registry": 1,
    "gpu_assignment": 1,
    "progress_adapters": 1,
    "discover": 1,
    "session_hint": 1,
    "command_audit": 1,
    "opencode_session_hint": 1
  },
  "cursor_scope": "run",
  "time_format": "RFC3339-with-offset",
  "truth_confidence_levels": ["high", "medium", "low", "unknown"],
  "remote_write_policy": {
    "research_decision_by_id_only": true,
    "arbitrary_shell": false,
    "opencode_http_proxy": false,
    "l3_policy_bypass": false,
    "writes_are_audited": true
  }
}
```

Bridge 不应通过 `paper_repro_version` 猜功能；只根据 `capabilities` 启用功能。

## 3. discover：无需预先知道项目路径

```bash
paper-repro remote discover --active --json
```

Bridge 可先找到活跃 workspace/run，再读取该 run 的 snapshot。

`workspace_id` 是跨系统持久主键：新项目生成随机 ID；旧 v2.1 项目首次升级时沿用旧路径哈希 ID 后持久化。目录移动后 ID 不变；如果整个 `.paper-repro` 被复制成两个同时存在的工作区，下一次注册会为新副本生成新的 ID，避免身份冲突。

## 4. snapshot：业务事实快照

```bash
paper-repro --workspace /srv/project remote snapshot --json
```

主要字段：

```json
{
  "schema_version": 1,
  "workspace": "/srv/project",
  "workspace_id": "ws-...",
  "run": {
    "run_id": "...",
    "state": "running",
    "started_at": "...",
    "elapsed_seconds": 1234
  },
  "pipeline": {
    "current_stage": "execution",
    "stage_index": 6,
    "stage_total": 8,
    "completed_stages": 5,
    "percent": 62.5
  },
  "tasks": {
    "active": [],
    "queued": [],
    "recent_completed": []
  },
  "gpu_assignments": {
    "0": {
      "task_id": "TASK-...",
      "task_ids": ["TASK-..."],
      "role": "current-reproduction",
      "assignment_source": "paper-repro",
      "confidence": "high",
      "integrity": "ok",
      "updated_at": "2026-08-10T10:20:00+00:00"
    }
  },
  "decisions": {
    "pending_count": 0,
    "blocking_count": 0
  },
  "blockers": {"active_count": 0},
  "opencode": {
    "session_id": "ses_xxx",
    "directory": "/srv/project",
    "hint_only": true
  }
}
```

注意：`pipeline.percent` 是 8 阶段流水线完成度，不是某个 GPU task 的 `progress.percent`。

默认不返回完整 task command、task cwd 和 Conda prefix。Bridge 通常应自行执行 `nvidia-smi` 获取利用率/显存/温度/功耗；仅诊断时可：

```bash
paper-repro remote snapshot --include-telemetry --json
```

确实需要完整 task 命令时：

```bash
paper-repro remote snapshot --include-command --json
```

## 5. Event cursor 是 run-scoped

这是 v2.1 最重要的兼容约定之一。

首次：

```bash
paper-repro --workspace /srv/project remote events --json
```

返回：

```json
{
  "schema_version": 1,
  "run_id": "RUN-A",
  "cursor_scope": "run",
  "after": null,
  "cursor_found": true,
  "events": [],
  "next_cursor": "EVT-000000000123",
  "has_more": false
}
```

Bridge 必须保存：

```text
(workspace_id, run_id, event_id)
```

`workspace_id` 从 v2.2 起是持久身份：新项目生成随机 ID；旧 v2.1 项目第一次升级时沿用旧路径哈希 ID 并持久化。项目目录之后迁移不会改变该 ID。

而不是只保存 `event_id`。新 run 会重新从较小的 EVT 序号开始；`run_id` 改变时必须重置 cursor。

如果传入的 cursor 在当前 run 中不存在：

```json
{
  "cursor_found": false,
  "events": []
}
```

此时 Bridge 应丢弃旧 cursor，重新取一次 snapshot，再从当前 run 的事件流起点/当前 cursor 开始。

## 6. 事件类型

核心语义事件包括：

```text
run.started
run.stage_changed
run.completed
run.failed

task.created
task.started
task.progress
task.completed
task.failed
task.timeout
task.cancelled

gpu.assigned
gpu.released

decision.created
decision.resolved

blocker.created
blocker.resolved

remote.command.queued
remote.command.dispatched
remote.command.accepted
remote.command.completed
remote.command.failed
remote.command.expired
remote.command.cancelled
```

OpenCode 自己的 message/tool/SSE event 继续由 Bridge 直接消费 OpenCode Server。

## 7. 研究决策

查询：

```bash
paper-repro --workspace /srv/project remote decisions --json
```

每项包含稳定的 `decision_id`、`option.id`、等级、阶段、是否 blocking、推荐项、是否允许 remember。

提交：

```bash
paper-repro --workspace /srv/project \
  remote decide DEC-123 smoke-test --json
```

首次成功：

```json
{
  "ok": true,
  "code": "resolved",
  "decision_id": "DEC-123",
  "resolved_option": "smoke-test",
  "state": "resolved"
}
```

重复提交相同结果：

```json
{
  "ok": true,
  "code": "already_resolved",
  "state": "already_resolved",
  "resolved_option": "smoke-test",
  "conflict": false
}
```

如果另一个客户端已经选择不同结果，返回 `code=already_resolved + conflict=true + resolved_option/requested_option`，退出码 4。Bridge 不应覆盖已经完成的人工决策，也不应解析自由文本判断冲突。

OpenCode permission 使用 `ocp:*` 展示命名空间；paper-repro research decision 建议使用 `prd:*` 展示命名空间。底层 ID 本身保持原样。

## 8. OpenCode session hint

paper-repro 只保存“提示”，不宣称 session 一定仍有效。

```bash
paper-repro --workspace /srv/project remote session bind \
  --session-id ses_xxx \
  --directory /srv/project \
  --json
```

查看：

```bash
paper-repro --workspace /srv/project remote session show --json
```

清除：

```bash
paper-repro --workspace /srv/project remote session clear --json
```

Bridge 仍应按以下顺序选择实时 session：

```text
有效的显式 session_id hint
→ directory/workspace 精确匹配
→ active/busy session
→ 用户选择
```

不要只按“最新 session”盲选。

## 9. Bridge → OpenCode 写操作审计

paper-repro 不代理 OpenCode HTTP。但 Bridge 可以记录脱敏元数据：

```bash
paper-repro --workspace /srv/project remote command record \
  --request-id RCMD-123 \
  --target opencode \
  --type prompt \
  --state queued \
  --requires-idle \
  --idempotency-key abc123 \
  --summary '当前任务结束后执行验证' \
  --json
```

后续状态：

```bash
... --state dispatched
... --state accepted
... --state completed
# 或进入 failed / expired / cancelled
```

`accepted` 只表示远端系统接受了请求，不能当作 `completed`。`completed/failed/expired/cancelled` 属于终态，写入后不能再改写为其他状态。

查看：

```bash
paper-repro remote command list --json
```

只应记录：request/session/type/state/idempotency key、脱敏摘要和可选 payload SHA256。不要把完整 prompt、Token 或服务器认证信息写入 paper-repro。

## 10. OpenCode 原生交互边界

Remote Bridge 应直接使用当前 OpenCode Server 的公开能力完成：

```text
session/status/todo/messages/children
permission reply
prompt / prompt_async
slash command
SSE event
```

paper-repro 不复制 OpenCode Server API，不硬编码未公开的 question reply route，不提供 `remote arbitrary-shell`。

## 11. Bridge 推荐消费循环

推荐使用自适应频率，而非固定 30 分钟/1 分钟：

```text
连接/重连：capabilities → discover → snapshot → OpenCode health/session

交互中 / 有 active task / waiting-decision：
  events 2–10 秒一次（或按 SSH/MCP 成本调整）

普通执行：
  events 10–30 秒一次
  snapshot 2–5 分钟一次用于纠偏

长期 idle：
  逐步退避到 30–120 秒

run_id 改变 / cursor_found=false / schema error：
  立即重新 snapshot，并重置 event cursor
```

OpenCode 自己的实时 activity 优先使用 SSE/event，不要为了看状态向 busy Agent 注入 `/repro-status`。

## 12. 安全边界

- OpenCode Server 继续只监听 loopback，远程通过 SSH tunnel；
- paper-repro snapshot/events 不包含 Token/password；
- Bridge 不暴露任意 SSH shell；
- `remote decide` 只能选择现有 decision 的现有 option；
- L3/不可逆决策仍受 paper-repro 决策治理；
- Remote command audit 不等于 OpenCode HTTP 代理；
- 所有远程写操作建议带 idempotency key；
- 远程状态若继续转发到第三方服务，Bridge 应进一步脱敏 workspace path、日志路径和项目名称。
