# v2.1.0 Remote Bridge 适配验证记录

## 验证范围

本版本主要验证远程契约，不改变 v2.0 Scheduler/GPU 核心调度算法。

## 已通过

1. `python -m py_compile scripts/reproctl.py scripts/runtime_engine.py`
2. `python tests/runtime_engine_test.py`
   - GPU pool 边界；
   - 两卡候选分配；
   - tqdm / REPRO_PROGRESS；
   - run-scoped event cursor page。
3. `python tests/remote_contract_test.py`
   - capabilities handshake；
   - remote decision schema；
   - 首次 resolve；
   - 重复相同 decision 幂等；
   - 冲突 decision 不覆盖；
   - OpenCode session hint；
   - snapshot JSON Schema；
   - CPU runtime task 完成后进入 recent_completed；
   - missing event cursor；
   - decision/task semantic event；
   - remote command audit/idempotency metadata。
4. JSON Schema 由测试使用 `jsonschema` 实际校验：
   - remote_capabilities.schema.json
   - remote_snapshot.schema.json
   - remote_events.schema.json
   - remote_decisions.schema.json
   - remote_command_audit.schema.json
5. `bootstrap.sh` 在临时 control Conda/Home/XDG 配置目录执行 `PAPER_REPRO_SKIP_DEPENDENCIES=1` 覆盖安装通过，安装版本为 2.1.0。
6. 源码隐私检查：包内未出现适配输入文档中的真实项目路径、项目名和模型运行示例。

## 未在本地替用户验证

- 真实 Remote Bridge SSH/MCP 链路；
- 用户服务器上的 OpenCode HTTP session/permission/prompt/command；
- 真实多机/容器 PID namespace；
- 实际 WorkBuddy UI；
- 真实双 GPU/四 GPU CUDA 工作负载（该部分沿用 v2.0 调度内核，应在用户服务器做 smoke run）。

## 已知说明

旧的全量 `tests/smoke_test.sh` 在当前隔离执行环境中会在已有 feedback-bundle 流程处长时间运行，未作为本次 Remote Bridge release gate。本版本新增/修改部分均由独立 remote contract test、runtime engine test、静态编译和临时覆盖安装进行验证。
