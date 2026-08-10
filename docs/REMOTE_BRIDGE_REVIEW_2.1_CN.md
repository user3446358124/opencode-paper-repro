# Remote Bridge v1.0 协议评审与 paper-repro v2.1 适配结果

## 结论

协议总体设计正确，尤其是三条边界应保留：

1. paper-repro 是复现业务事实源；
2. OpenCode 原生 permission/question/prompt/command 由 Bridge 直接处理；
3. `nvidia-smi/ps/proc` 只做遥测/诊断，不反推业务任务。

v2.1 已补齐 capabilities、幂等 decision、run-scoped event cursor、session hint、command audit、语义事件镜像，并将 GPU raw telemetry 从默认 snapshot 中拆出。

## 建议 Remote Bridge 调整

### 1. event cursor 必须绑定 run_id

不要只保存：

```text
EVT-000000000123
```

应保存：

```text
workspace_id=ws-...
run_id=...
event_id=EVT-...
```

新 run 重置 cursor。

### 2. 启动时先 capabilities

不要通过 `paper-repro --version` 写死分支。先调用：

```bash
paper-repro remote capabilities --json
```

缺少某 capability 时才启用旧版 fallback。

### 3. 固定 30min snapshot / 1min events 不建议写死

这在等待人工决策时偏慢，在长期 idle 时又偏频繁。建议自适应退避：活跃时 2–30 秒事件轮询，2–5 分钟 snapshot 纠偏；idle 时逐步退避。

### 4. prompt_async 的 HTTP 204 只能表示 accepted

不要仅因为请求返回成功就把 Remote Command Envelope 标为 `completed`。`completed` 应由 Bridge 根据后续 message/event/todo/session activity 相关性确认；无法可靠确认时停在 `accepted`。

### 5. OpenCode session_id 只能是 hint

session 可能已退出或被替换。Bridge 应验证 hint，再按 directory → active session → 用户选择回退。

### 6. workspace path 的隐私层级

paper-repro 的 SSH 内部 snapshot 保留 workspace 路径，便于 session 匹配。但 Bridge 如果把状态转发到云端/聊天/外部日志，应优先显示 `workspace_id` 或 basename，并按需隐藏绝对路径。

### 7. GPU raw telemetry 继续由 Bridge 获取

paper-repro 默认只输出语义 assignment。Bridge 用 `nvidia-smi` 补利用率、显存、温度和功耗。诊断时才请求 `--include-telemetry`。

### 8. OpenCode question API 继续 feature-detect

不要让 paper-repro 实现 question reply 代理。Bridge 从当前 OpenCode `/doc` OpenAPI 检测；没有稳定 route 时使用当前版本原生机制或等待 TUI 处理。

### 9. 不暴露 arbitrary shell

诊断命令使用 Bridge 自己的 allowlist；复现业务操作走 paper-repro CLI；Agent 指令走 OpenCode prompt/command。

### 10. 远程写操作都使用 idempotency key

Bridge 对 prompt/command 等生成 request_id + idempotency_key，并用 `paper-repro remote command record` 记录状态。完整 prompt 不进入 paper-repro 审计文件。

## paper-repro 端新增接口

```bash
paper-repro remote capabilities --json
paper-repro remote session show --json
paper-repro remote session bind --session-id ... --directory ... --json
paper-repro remote session clear --json
paper-repro remote command record ... --json
paper-repro remote command list --json
```

已有接口增强：

```bash
paper-repro remote snapshot --json
paper-repro remote events --after EVT-... --json
paper-repro remote decisions --json
paper-repro remote decide DEC OPTION --json
```

## 验收

运行：

```bash
python tests/remote_contract_test.py
python tests/runtime_engine_test.py
```

重点验证：能力握手、decision 幂等与冲突、session hint、snapshot schema、cursor missing、command audit。

## OpenCode 官方接口边界核对（2026-08-10）

当前 OpenCode Server 官方文档公开了 `/doc` OpenAPI、session/status/message、`prompt_async`、slash command、permission reply 与 SSE `/event` 等接口；因此 Bridge 直接对接 OpenCode Server、paper-repro 不做代理是合适的职责划分。

参考：

- https://opencode.ai/docs/server/
- https://opencode.ai/docs/permissions/
- https://opencode.ai/docs/tools/

`question` tool 本身属于 OpenCode 原生工具；如果当前实例的 `/doc` 没有稳定的 question reply route，Bridge 应 feature-detect，而不是调用 paper-repro 私自实现的兼容接口。
