# v2.2.1 安全复检问题修复对照

本文件对应 v2.2.0 全系统可执行性与安全性复检中发现的问题，记录 v2.2.1 的实际修复状态。

| 原问题 | 等级 | v2.2.1 处理 | 状态 |
|---|---:|---|---|
| 项目进程继承统一配置 Token/API Key | P0 | Runtime/短命令默认清洗 secret/control env；只有 workspace 先授权变量名、具体任务再次声明 `secret_env` 才注入 | 已修复 |
| Conda 不是不可信代码安全沙箱 | P0 | 默认 bubblewrap fail-closed；最小文件系统可见性，不挂载宿主 `/`；隐藏 HOME 和真实 `.paper-repro`；只暴露必要系统路径、当前项目/项目 Conda、任务交换目录、GPU 与显式数据根 | 已实现；真实服务器 bwrap 仍需现场验证 |
| 项目可篡改 `.paper-repro/config.json` 放宽自身权限 | P0（追加发现） | sandbox 中以 tmpfs 覆盖真实 `.paper-repro`，仅回挂 cache 和单任务交换目录；真实 decision/task registry/security policy 不可见 | 已修复 |
| GitHub 发布跟随嵌套 symlink | P0 | allowlist 整树递归 symlink 扫描，发现任一链接立即 fail-closed | 已修复 |
| 安装/卸载 `rm -rf` 路径保护不足 | P1 | canonical path、危险路径拒绝、默认限定 control Conda share、卸载必须校验 install marker 与 install_home 一致 | 已修复 |
| 日志脱敏规则分散/不完整 | P1 | Python 控制器与 Runtime 共用 `security.py`；插件增加 Bearer/CLI 参数/常见 token/当前真实 secret 精确替换 | 已修复 |
| OpenCode 可读取统一配置/SSH/云凭据 | P1 | permission + plugin 双层阻断；扩展到 GH/HF/Docker/Kube/npm/pypi/conda/system credential；控制模式初始化前即生效 | 已修复主要已知路径 |
| Bash 可读 `/proc/$PPID/environ` 或调用 `secrets exec` | P1（追加发现） | plugin 阻断 `/proc/*/environ` 与 `paper-repro secrets exec/edit` | 已修复已知路径 |
| 下载器可写任意绝对路径 | P1 | 默认仅 workspace/cache；外部目录必须用户 `security download-root add ... --yes`，同一白名单用于 sandbox 外部数据挂载 | 已修复 |
| 控制层依赖浮动 latest | P1 | OpenCode/Node/bubblewrap/gh/Brave/Python 直接依赖固定版本；新增 `dependency-pins.json` | 大幅改善；非 artifact/hash 完全锁定 |
| 旧状态文件可能 644/目录 755 | P2 | 新写入默认 umask 077；新增 `security permissions repair --scope ... --yes` 迁移旧状态 | 已修复 |

## 仍然明确保留的边界

1. `trusted-off` 不是安全沙箱，只用于人工审查可信仓库。
2. sandbox 默认网络为 `on`，因为部分论文执行需要联网；私有数据场景建议设置 `--network off`。
3. workspace 本身仍允许项目进程写入，以兼容编译/输出；`.git/.opencode/opencode.jsonc/AGENTS.md` 被额外只读保护。对完全敌对代码的“源目录只读 + 精确输出目录”模式尚未作为默认实现。
4. Python 传递依赖、远程 MCP 服务端和下载 artifact 未做跨平台 hash 级完全锁定；v2.2.1 只声明直接版本固定。
5. 本发布环境没有真实 `bwrap`/NVIDIA GPU，因此 bubblewrap 命令生成、fail-closed 和边界逻辑已测试，但真实 CUDA+bwrap 组合需要服务器 smoke run。
