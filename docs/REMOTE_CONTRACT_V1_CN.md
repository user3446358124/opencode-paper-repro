# paper-repro × Remote Bridge — Remote Contract v1

**状态：Frozen**  
**paper-repro 首个完整实现版本：2.2.0**

Remote Contract v1 是 paper-repro 与 Remote Bridge 之间的薄协议层。双方只约定可观察的 JSON 语义，不约定内部目录、调度实现、OpenCode 私有兼容代码或轮询频率。

## 1. 永久职责边界

- **paper-repro**：run / stage / task 业务事实、GPU assignment 语义、任务进度/ETA、blocker、研究 decision、任务日志/产物绑定。
- **OpenCode**：Agent session、模型推理、tool、permission、question、prompt、slash command。
- **Remote Bridge**：SSH/MCP 传输、OpenCode HTTP adapter、GPU 原始遥测、状态合并、事件转发与兼容 fallback。
- **WorkBuddy/上层客户端**：自然语言入口、展示、用户选择回传。

paper-repro **不代理 OpenCode HTTP、不模拟键盘、不暴露 arbitrary shell**。

## 2. Contract v1 的六个核心协议面

```text
1. capabilities
2. snapshot
3. events
4. decisions / decide
5. session hint
6. command audit
```

`remote discover` 是兼容的发现扩展，不要求 Bridge 把 paper-repro 内部 registry 当协议。

## 3. 能力握手

Bridge 启动时必须先调用：

```bash
paper-repro remote capabilities --json
```

不得通过 `paper_repro_version >= ...` 推测能力。

Contract v1 约定：

- consumer 必须忽略不认识的新增字段；
- 字段在同一 capability major 内不能悄悄改变语义；
- 如语义必须破坏性变化，先提升对应 capability version；
- 两个仓库不要求同步发版。

## 4. 跨系统主键

双方认以下 ID：

```text
workspace_id
run_id
task_id
event_id
decision_id
request_id
idempotency_key
```

### workspace_id

`workspace_id` 是持久身份。新项目生成随机 `ws-xxxxxxxxxxxx` 并写入 `.paper-repro/config.json`。目录移动后 ID 不变。

从 v2.1 升级的项目首次使用 v2.2 时，为避免已有 Bridge 状态失效，会先沿用 v2.1 的路径哈希 ID，再持久化；之后移动目录也不再变化。

### task_id

**同一个 run 生命周期内永不复用。** retry 是原 task 的生命周期继续，不创建同 ID 的第二个业务任务。

### event_id

只保证**同一个 run 内单调、不复用**。Bridge cursor 必须保存：

```text
(workspace_id, run_id, event_id)
```

`run_id` 变化时必须丢弃旧 cursor 并重新 snapshot。

## 5. 状态真实性等级

统一：

```text
high
medium
low
unknown
```

任务进度至少暴露：

```json
{
  "current": 309,
  "total": 500,
  "percent": 61.8,
  "eta_seconds": 3885,
  "source": "result-jsonl-line-count",
  "confidence": "high",
  "updated_at": "2026-08-10T10:20:00+00:00"
}
```

Bridge 不需要知道 paper-repro 如何得到该数据。

GPU 业务归属由 paper-repro 输出：

```json
{
  "task_id": "TASK-...",
  "assignment_source": "paper-repro",
  "confidence": "high",
  "integrity": "ok"
}
```

GPU 利用率/显存/温度/功耗仍由 Bridge 的 `nvidia-smi` 遥测得到。

## 6. ETA 三个概念永久分离

```text
timeout_seconds
startup_estimate_seconds
eta_seconds
```

`timeout_seconds` 永远不是 ETA；`startup_estimate_seconds` 永远不是实时 ETA；没有可靠进度时 `eta_seconds = null`。

## 7. 时间格式

所有 Remote Contract 对外时间统一为：

```text
RFC3339 / ISO-8601 + 显式 timezone offset
```

示例：

```text
2026-08-10T18:19:00+08:00
2026-08-10T10:19:00+00:00
```

不输出无 timezone 的裸时间作为协议时间。

## 8. 研究决策与 OpenCode 原生交互

命名空间建议：

```text
prd:* → paper-repro research decision
ocp:* → OpenCode permission
ocq:* → OpenCode question
```

paper-repro 只拥有研究 decision：

```bash
paper-repro remote decisions --json
paper-repro remote decide DECISION_ID OPTION_ID --json
```

OpenCode permission/question 仍由 Bridge 直接通过当前 OpenCode 实例处理。

### decide 幂等语义

首次成功：

```json
{"ok":true,"code":"resolved","state":"resolved","resolved_option":"smoke-test"}
```

重复相同选择：

```json
{"ok":true,"code":"already_resolved","state":"already_resolved","resolved_option":"smoke-test","conflict":false}
```

已经被其他客户端选择不同结果：

```json
{"ok":false,"code":"already_resolved","state":"already_resolved","resolved_option":"smoke-test","requested_option":"full-run","conflict":true}
```

Bridge 不解析自由文本判断冲突。

## 9. Remote Command 生命周期

统一：

```text
queued
  ↓
dispatched
  ↓
accepted
  ↓
completed
```

异常终态：

```text
failed
expired
cancelled
```

`accepted` **不等于** `completed`。例如 OpenCode `prompt_async` 被服务端接受后，Bridge 只能记录 `accepted`；真正完成必须由后续 OpenCode 状态/事件确认。

paper-repro 的 `remote command record` 只保存脱敏审计元数据，不发送 OpenCode HTTP，也不保存完整 prompt。

终态一旦写入，不允许再改成另一状态。

## 10. Session Hint

paper-repro 可以保存：

```text
session_id
directory
source
updated_at
hint_only=true
```

Bridge 必须按以下顺序验证：

```text
session hint
→ 验证 session 是否仍存在
→ workspace/directory 精确匹配
→ active/busy session
→ 仍有多个时让用户选择
```

不能永久相信旧 session ID。

## 11. 兼容与弃用

Contract v1 采用“加字段兼容、改语义升级 capability”的规则。

v2.1 的以下兼容项暂时保留：

```text
capabilities.opencode_session_hint
snapshot.task_list
snapshot.gpu
```

canonical 字段分别是：

```text
capabilities.session_hint
snapshot.tasks
snapshot.gpu_assignments
```

这些别名在 Remote Contract v2 之前不会删除。

## 12. 明确不统一的内容

以下内容不属于 Contract：

- `.paper-repro` 内部目录结构；
- paper-repro scheduler/task executor 内部实现；
- Bridge 的 `nvidia-smi` 解析方式；
- Bridge 的轮询/退避频率；
- WorkBuddy 的 Markdown/Skill；
- OpenCode HTTP 私有版本兼容代码。

## 13. Contract Test

paper-repro 仓库必须通过：

```bash
python tests/remote_contract_test.py
```

至少验证：

- capabilities handshake；
- JSON Schema；
- workspace ID 持久化；
- task ID 不复用；
- run-scoped monotonic event ID；
- event sequence 恢复；
- RFC3339 offset 时间；
- decision 幂等/冲突；
- session hint；
- command audit 生命周期与 idempotency；
- snapshot 的 progress confidence；
- 新字段可被旧 consumer 忽略。

Contract test 是发布门禁，不应被自我迭代流程跳过。
