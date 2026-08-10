# v2.2.1 发布前验证记录

验证目标：确认 v2.2.0 安全复检问题的修复不会破坏 Runtime、GPU/Remote Contract、安装升级、自我迭代和 GitHub 发布安全链路。

## 已通过

- `python -m py_compile scripts/security.py scripts/runtime_engine.py scripts/reproctl.py ...`
- `bash -n bootstrap.sh scripts/uninstall.sh tests/smoke_test.sh`
- `schemas/*.json` / `configs/*.json` 严格 JSON 解析
- `repro-audit.ts` TypeScript 语法检查（使用本地最小类型 stub，不等价于真实 OpenCode SDK 集成测试）
- `python tests/security_hardening_test.py` → `SECURITY_HARDENING_TEST_OK`
- `python tests/runtime_engine_test.py` → `RUNTIME_ENGINE_TEST_OK`
- `python tests/remote_contract_test.py` → `REMOTE_CONTRACT_TEST_OK`
- 完整 `bash tests/smoke_test.sh` → `smoke test passed`，exit code 0
- 隔离 HOME + fake control Conda 的 bootstrap/uninstall → `ISOLATED_BOOTSTRAP_UNINSTALL_OK`
- 完整 bootstrap 默认固定 `bubblewrap=0.11.2` 安装到控制 Conda；skip-dependencies 路径只更新代码并保持 fail-closed
- GitHub 公开源码快照隐私扫描：129 files，0 blockers，0 warnings
- 源码树 symlink 数量：0

## Security Hardening gate 实际覆盖

- 父进程临时高权限 Token 默认无法被项目任务读取
- 任务级显式 secret 注入仅在授权后可用
- 无 bwrap 时 auto/required fail-closed
- sandbox 不挂载宿主整个 `/`
- HOME/控制状态隐藏；cache + task exchange 单独暴露
- project/control Conda 分离与 sibling env 隐藏规则
- 外部数据根显式授权
- sandbox 配置若落在项目可写路径则拒绝
- 嵌套 symlink 发布阻断
- 私有文件权限与旧状态权限 repair
- 安装/卸载危险路径阻断
- OpenCode sensitive read/env/proc/secrets-exec 防护静态门禁
- 自我迭代测试必须包含 security/runtime/remote contract gates

## 当前环境无法完成、需服务器现场验证

- 真实 bubblewrap namespace + 当前服务器内核/userns 策略
- 真实 NVIDIA/CUDA/NCCL 在 bubblewrap 内运行
- 真实双卡 DDP/torchrun 长任务
- 用户真实 OpenCode TUI + Provider/DeepSeek + MCP
- 真实 GitHub OAuth/PAT push/PR

这些项目未被声明为已验证。缺少 bwrap 时生产默认会 fail-closed，而不是降级后继续执行。
