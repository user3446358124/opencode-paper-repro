# 测试说明

## 自动冒烟测试

```bash
bash tests/smoke_test.sh
```

覆盖：

- Git 工作区与子目录自动发现；
- run 初始化；
- 独立项目 Conda 配置；
- 通过 `conda run -p` 执行项目命令；
- `REPRO_PROGRESS` 解析；
- 8 步 pipeline 状态；
- HTTP 下载、SHA256 和产物登记；
- 失败命令与问题文档；
- 脱敏反馈包。

## 安装器检查

在临时控制 Conda 中使用：

```bash
PAPER_REPRO_SKIP_DEPENDENCIES=1 bash bootstrap.sh
```

检查：

```text
~/.config/opencode/commands/reproduce.md
~/.config/opencode/tools/repro.ts
~/.config/opencode/plugins/repro-audit.ts
~/.local/bin/paper-opencode
~/.local/bin/paper-repro
```

## 真实服务器验证

```bash
paper-repro --version
paper-opencode --version
cd /path/to/project
paper-repro env show
paper-repro doctor
paper-opencode
```

在 OpenCode 中确认 `/reproduce`、`/repro-env` 和 `/repro-status` 可见。


## 决策层测试

冒烟测试覆盖低风险自动记录、L2 待确认、`repro_exec` 退出码 3、等待决策不进入系统问题、用户确认和 workspace 偏好复用。


## Remote Contract v1 发布门禁

```bash
python tests/remote_contract_test.py
python tests/runtime_engine_test.py
```

`remote_contract_test.py` 验证 capabilities、持久 workspace_id、run-scoped event cursor、event sequence 恢复、task ID 不复用、RFC3339 时间、decision 幂等/冲突、session hint、command audit 生命周期/idempotency 和 Schema。

该测试属于 Remote Contract v1 的兼容性门禁；自我迭代流程与 GitHub CI 都必须执行，不能因为普通 smoke test 已通过而跳过。
