# v2.2.0 Remote Contract v1 验证记录

本版本将 Remote Bridge 协议从“约定方向”提升为正式冻结的 Contract v1。

## 已通过

1. `python -m py_compile scripts/reproctl.py scripts/runtime_engine.py tests/remote_contract_test.py tests/runtime_engine_test.py`；
2. 所有 `schemas/*.json` 与 `configs/*.json` 可离线解析；
3. `python tests/remote_contract_test.py` → `REMOTE_CONTRACT_TEST_OK`；
4. `python tests/runtime_engine_test.py` → `RUNTIME_ENGINE_TEST_OK`；
5. 隔离 HOME / XDG / 临时控制 Conda 中执行 `PAPER_REPRO_SKIP_DEPENDENCIES=1 bash bootstrap.sh`，安装后 `paper-repro --version` 为 2.2.0；
6. 安装源码快照包含 `docs/REMOTE_CONTRACT_V1_CN.md` 与新增 Remote Contract Schema；
7. 公开源码隐私回归扫描未发现真实用户工作区绝对路径、PAT/HF/OpenAI 风格真实密钥；旧手册残留的真实风格绝对路径示例已统一改为 `/srv/projects/example-paper`；
8. Remote Contract test 覆盖：
   - capabilities frozen handshake；
   - 持久 `workspace_id`；
   - `task_id` 同 run 不复用；
   - run-scoped monotonic `event_id`；
   - `event-seq.txt` 丢失后的序号恢复；
   - RFC3339 + timezone offset；
   - `startup_estimate_seconds` 与实时 `eta_seconds` 严格分离；
   - decision 首次解决 / 相同重试 / 冲突；
   - session hint；
   - command audit lifecycle / terminal state / idempotency；
   - progress confidence 与 snapshot Schema。

## 完整 smoke test

`tests/smoke_test.sh` 在当前沙箱中执行时间较长，单次 240 秒窗口内未完整结束，因此本次没有声明“完整 smoke test 已通过”。从 `bash -x` 追踪看，测试已通过 Remote Contract、decision、下载、预期失败/blocker、code index、feedback、中文 status 和统一 secrets 等阶段，并继续进入模型/MCP/后续发布相关测试，没有在本次新增 Remote Contract 逻辑处失败。

GitHub CI 仍保留完整 smoke test，同时新增独立的 Remote Contract v1 与 Runtime Engine release gate；因此协议破坏不会依赖长 smoke 才被发现。

## 尚需实际服务器联调

- Remote Bridge 真实 SSH/MCP 消费；
- 当前 OpenCode Server session/permission/prompt/command adapter；
- 两卡/多卡真实 CUDA 调度；
- Bridge 在 run 切换时保存并重置 `(workspace_id, run_id, event_id)` cursor。
