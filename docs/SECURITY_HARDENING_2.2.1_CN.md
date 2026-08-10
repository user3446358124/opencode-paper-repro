# v2.2.1 安全加固说明

v2.2.1 是针对 v2.2.0 全系统可执行性/安全性复检结果的加固版本。核心原则是：**控制平面可以持有凭据，但论文项目代码默认既看不到凭据，也看不到真实用户 Home；任何降低隔离级别的操作必须由用户显式完成。**

## 1. 项目任务默认无密钥

持久 Scheduler 启动项目任务前会清洗环境变量。名称符合 `TOKEN / API_KEY / SECRET / PASSWORD / AUTHORIZATION / CREDENTIAL / PRIVATE_KEY` 等模式的变量，以及 paper-repro 配置位置、SSH agent 等控制平面变量，默认不会进入项目进程。

如某个任务确实需要例如 `HF_TOKEN`，先由用户对当前 workspace 明确授权：

```bash
paper-repro security secret allow HF_TOKEN --yes
```

然后任务才能声明：

```bash
paper-repro runtime submit ... --secret-env HF_TOKEN
```

授权只决定“这个 workspace 可以请求该变量”；具体任务仍需显式写 `--secret-env`。取消：

```bash
paper-repro security secret revoke HF_TOKEN
```

## 2. OS 级项目执行沙箱

默认策略：

```text
sandbox.mode = auto
sandbox.backend = auto
```

当前实现使用 Linux `bubblewrap` (`bwrap`)。完整 `bootstrap.sh` 会把固定版本的 bubblewrap 安装到**控制 Conda**，不调用 sudo/apt；使用 `PAPER_REPRO_SKIP_DEPENDENCIES=1` 覆盖升级时不会自动补装。若 `bwrap` 不可用或内核禁止所需 namespace，`auto/required` 都会 **fail closed**。

查看：

```bash
paper-repro security show
```

对于已经人工审查、完全信任的仓库，可以由用户显式关闭 OS 沙箱：

```bash
paper-repro security sandbox set --mode trusted-off --yes
```

这会退化为“Conda + 环境变量清洗”，不能阻止同 Linux 用户读取其他文件，因此只适用于可信仓库。

沙箱启用时：

- **不挂载宿主机整个 `/`**；只暴露 `/usr`、必要动态链接/TLS/NSS 配置、`/sys` 等运行必需系统路径；
- 不暴露 `/etc/shadow`、`/etc/gshadow`、`/etc/sudoers` 等系统凭据文件；
- 真实 `$HOME` 完全不可见，`HOME` 与 `XDG_CONFIG_HOME` 指向沙箱临时目录；
- 当前 workspace 可写，但宿主真实 `.paper-repro` 会被 tmpfs 覆盖隐藏；
- 只重新暴露 `.paper-repro/cache` 和任务专属 `REPRO_RUN_DIR` 交换目录，任务看不到真实 decisions/task registry/config；
- 当前 project Conda 可写，control Conda/Conda base 只读；Conda base 的 sibling envs 被隐藏；project Conda 与 control Conda 相同会直接拒绝；
- `.git`、`.opencode`、`opencode.jsonc`、`AGENTS.md` 在项目进程中只读；
- 只按调度结果暴露选中的 NVIDIA device node；
- workspace 外的模型/数据目录只有用户先 `security download-root add ... --yes` 后才会挂载；
- `/proc` 使用独立 PID namespace，不能读取宿主 OpenCode/父进程环境；
- 默认共享网络；可设置 `--network off`。

### 2.1 安全策略本身不可由项目伪造

虽然 workspace 中存在 `.paper-repro/config.json`，但 sandbox 内的 `.paper-repro` 是临时覆盖层。第三方项目进程修改该路径只会修改沙箱临时文件，不会改变宿主上的 secret allowlist、`trusted-off`、GPU policy、decision 或 Remote Contract 状态。

`REPRO_RUN_DIR` 在 sandbox 中映射到单任务交换目录，不是宿主真实 run 根目录。

## 3. OpenCode 敏感读取防护

`opencode.jsonc` 和 `repro-audit.ts` 双层拒绝以下路径：

- `~/.config/paper-repro/**`
- `~/.ssh/**`
- `~/.git-credentials`
- `~/.netrc`
- `~/.aws/**`
- `~/.config/gcloud/**`
- `~/.local/share/opencode/auth.json`
- `~/.kube/**`、`~/.docker/**`、`~/.config/gh/**`、Hugging Face token
- `~/.npmrc`、`~/.pypirc`、`~/.condarc`
- `/etc/shadow`、`/etc/gshadow`、`/etc/sudoers`
- 非 example 的 `.env*`
- `/proc/*/environ` 与 `paper-repro secrets exec/edit` 的 Bash 绕过路径

这些阻断在 **paper-repro 控制模式启动后立即生效**，不依赖项目是否已经 `paper-repro init`。OpenCode 的 Bash 子进程还会将控制平面的 Token/API Key 类环境变量覆盖为空；事件日志会对当前进程中实际 secret 值再次做精确脱敏。

## 4. GitHub 发布 symlink fail-closed

公开快照复制前递归检查 allowlist 中的整个源码树。发现任何文件或目录 symlink 都会阻断发布，不再跟随链接读取目标内容。

## 5. 安装/卸载路径保护

`bootstrap.sh`：

- 拒绝 `/`、`$HOME`、`$CONDA_PREFIX` 作为安装目录；
- 默认只允许 `$CONDA_PREFIX/share/...`；
- 外部目录必须显式设置 `PAPER_REPRO_ALLOW_EXTERNAL_INSTALL_HOME=1`。

`uninstall.sh`：

- 同样拒绝危险路径；
- `rm -rf` 前必须存在有效 `install.json`；
- `install.json.install_home` 必须与实际卸载路径一致。

## 6. 下载写入边界

默认只允许写入：

- 当前 workspace；
- `.paper-repro/cache`。

需要额外数据盘时先由用户扩展：

```bash
paper-repro security download-root add /data/paper-assets --yes
```

移除：

```bash
paper-repro security download-root remove /data/paper-assets
```

## 7. 统一脱敏

Python 控制器与 Runtime 共用 `scripts/security.py`，覆盖：

- Authorization Bearer；
- `--api-key / --token / --password / --secret`；
- URL query secret；
- URL basic auth；
- GitHub PAT、HF token、OpenAI-style `sk-`、AWS access key；
- 统一配置中的实际 secret 原值、URL 编码、Base64 编码。

OpenCode 插件使用同类规则进行事件日志脱敏。

## 8. 默认私有文件权限

控制器和 Runtime 默认设置 `umask 077`。新创建的 JSON/JSONL 状态文件使用 user-only 权限，统一配置继续为 `600`。

旧 workspace 可以一次性修复历史权限：

```bash
paper-repro security permissions repair --scope workspace --yes
```

同时修复统一全局配置：

```bash
paper-repro security permissions repair --scope all --yes
```

目录设为 `700`，状态/配置文件设为 `600`；symlink 不跟随。

## 9. 控制层依赖固定

v2.2.1 默认固定：

- `opencode-ai==1.18.4`
- `nodejs=26.5.0`（Linux control Conda）
- `bubblewrap=0.11.2`（Linux control Conda）
- `gh=2.96.0`
- Python 控制依赖见 `configs/control-requirements.lock.txt`
- Brave Search MCP 固定为 `@brave/brave-search-mcp-server@2.1.0`
- 完整直接依赖清单见 `configs/dependency-pins.json`

环境变量仍允许高级用户覆盖部分固定版本，但默认安装不会再使用 `latest`。需要明确：v2.2.1 做到的是**直接依赖版本固定**，不是跨平台 artifact/hash 级完全锁定；Python 的传递依赖和远程 MCP 服务端仍可能随上游变化，因此系统不会宣称已经做到 bit-for-bit 供应链复现。

## 10. 永久安全回归门禁

新增：

```bash
python tests/security_hardening_test.py
```

覆盖：密钥继承、任务级显式授权、sandbox fail-closed、发布 symlink、私有文件权限、下载边界、危险安装/卸载路径，以及 OpenCode 敏感路径防护。
