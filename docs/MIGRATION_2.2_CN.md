# v2.1.0 → v2.2.0 覆盖升级说明

v2.2.0 不改变 v2.0 的 GPU Scheduler 核心，重点是把 paper-repro × Remote Bridge 的 **Remote Contract v1 正式冻结**。

## 升级

完全退出 OpenCode 后：

```bash
conda activate <paper-repro-control>
cd /path/to/opencode-paper-repro-starter-v2.2.0
PAPER_REPRO_SKIP_DEPENDENCIES=1 bash bootstrap.sh
hash -r
```

然后：

```bash
paper-repro --version
paper-repro remote capabilities --json
paper-repro doctor
```

版本应为 `2.2.0`，capabilities 中应出现：

```json
{"contract":{"name":"paper-repro-remote","major":1,"status":"frozen"}}
```

## 对现有 Remote Bridge 的影响

- `snapshot/events/decisions/session/command` 的 v2.1 字段继续兼容；
- canonical session capability 改为 `session_hint`，旧 `opencode_session_hint` 继续保留；
- `remote decide` 增加机器码 `code`、`resolved_option` / `requested_option`；
- command audit 新增 `cancelled`，并开始校验 terminal state；
- Bridge event cursor 应保存 `(workspace_id, run_id, event_id)`；
- consumer 必须忽略未知新增字段。

## workspace_id 迁移

旧 v2.1 工作区第一次在 v2.2 使用时，会把原路径哈希 ID 写入 `.paper-repro/config.json`。之后项目目录迁移，ID 保持不变。

新建项目直接生成持久随机 ID。

## 建议联调

```bash
python tests/remote_contract_test.py
python tests/runtime_engine_test.py
```
