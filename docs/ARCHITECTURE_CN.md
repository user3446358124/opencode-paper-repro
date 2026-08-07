# 0.3.0 架构说明：全局控制层与项目执行层

## 1. 设计目标

系统必须同时满足：

- 同一用户只安装一次 OpenCode 扩展和控制器；
- 项目之间依赖隔离；
- 不依赖当前 shell 是否正确激活；
- 所有执行命令可审计；
- 项目名称和目录结构不写死；
- 长任务显示阶段、任务、速度、ETA 与 GPU。

## 2. 三种环境身份

### 控制环境

保存于全局 `install.json`，运行：

- OpenCode；
- paper-repro；
- PDF 解析；
- 下载控制器；
- 状态界面；
- GPU 和日志采样。

### 项目执行环境

保存于：

```text
<workspace>/.paper-repro/config.json
```

所有 `repro_exec` 命令通过绝对 prefix 运行，不依赖 shell 激活状态。

### shell 环境

仅用于：

- `env set --active`；
- 状态界面提示；
- 发现可能的误操作。

它不决定实际实验命令的 Python。

## 3. 全局安装边界

“全局”指当前 Linux 用户，而不是整台服务器所有用户。

```text
~/.config/opencode
~/.local/bin
~/.local/share/opencode-paper-repro
~/.local/state/opencode-paper-repro
```

其他用户需要各自安装，root 与普通用户的配置也彼此独立。

## 4. 工作区解析

系统不使用固定项目名。所有 OpenCode 工具把 `context.worktree` 传给控制器；CLI 再结合显式参数、状态祖先和 Git 根目录确定工作区。

## 5. 环境锁定

执行前会验证：

- prefix 存在；
- 不是 Conda base；
- prefix 中存在 Python；
- Python 报告的 `sys.prefix` 与配置 prefix 一致；
- 默认不与控制环境相同。

最终执行命令：

```text
conda run --no-capture-output -p <prefix> bash -c <command>
```

## 6. 进度分层

- Workflow：9 个顶层步骤；
- Stage progress：当前顶层步骤内部进度；
- Task progress：当前命令或下载进度；
- GPU：独立定时采样。

分层避免把单个任务百分比混同于总体复现百分比。


## 决策治理层

控制器在工具权限层之上增加 L0–L3 语义决策分级。待确认决策持久化到 run 的 meta/report，并从 `repro_exec` 层阻止后续项目命令。详见 `DECISION_GOVERNANCE_CN.md`。
