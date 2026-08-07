# OpenCode Paper Reproduction Starter

面向“在新服务器上，使用 OpenCode 与可配置底座模型自动审计并复现论文代码”的可审计控制层。

当前版本：**1.0.0**

完整中文手册：[`USAGE_CN.md`](USAGE_CN.md)

模型能力路由：[`docs/MODEL_ROUTING_CN.md`](docs/MODEL_ROUTING_CN.md)

## 核心架构

系统明确区分三件事：

1. **用户级 OpenCode 扩展**：安装到当前 Linux 用户的 `~/.config/opencode/`，同一用户只需安装一次。
2. **控制 Conda 环境**：固定运行 OpenCode、当前底座模型和 `paper-repro`，推荐命名为 `paper-repro-control`。
3. **项目 Conda 环境**：每个论文项目独立创建或选择，只运行项目代码；配置保存在项目的 `.paper-repro/config.json`。

项目文件夹名与 Conda 环境名没有隐式关系。例如 `/srv/projects/example-paper` 只是工作区路径，可以使用名为 `lead-repro-py310` 的 Conda 环境。


## 主要功能

### 自适应人工决策

系统不再把“自动化”理解为所有选择都自动通过。默认使用 `balanced`：低风险、可逆且有明确默认项的操作自动执行并记录；会改变实验语义、成本、许可、外部状态或不可逆性的选择进入用户决策检查点。

```bash
paper-repro decisions policy show
paper-repro decisions policy set --scope workspace --mode balanced
paper-repro decisions list --pending
```

OpenCode 中：

```text
/repro-decisions
```

`paper-opencode --auto` 只自动批准 OpenCode 工具权限，不会绕过 paper-repro 的研究语义决策。详见 [`docs/DECISION_GOVERNANCE_CN.md`](docs/DECISION_GOVERNANCE_CN.md)。

### 一条命令生成代码阅读手册

```text
/repro-explain all
```

输出仓库概览、训练/评测/推理调用链、论文核心模块实现映射、数据与 tensor 流、配置实验说明、运行时证据和分层阅读顺序。详见 [`docs/CODE_EXPLAINER_CN.md`](docs/CODE_EXPLAINER_CN.md)。

### PDF 文本与视觉联合审计

默认 `targeted`：全文使用文本层提取精确文字和数值，同时对扫描页、实验表格页和核心方法图页进行视觉复核。是否真实调用视觉模型会写入 `paper_manifest.json` 的 provenance。详见 [`docs/PDF_HYBRID_AUDIT_CN.md`](docs/PDF_HYBRID_AUDIT_CN.md)。

### 系统反馈与项目阻塞分离

- 系统功能/优化问题：`SYSTEM_ISSUES.md`、`paper-repro issue`；
- 单个论文项目阻塞：`RUN_BLOCKERS.md`、`paper-repro blocker`；
- `paper-repro feedback` 默认只打包系统功能问题。


### 统一配置与密钥持久化

全局视觉 API、模型路由、MCP 开关和 Token 统一保存在：

```text
~/.config/paper-repro/config.json
```

文件权限为 `600`，`paper-opencode` 会在启动时自动加载，不再需要把 Token 写入 `.bashrc`：

```bash
paper-repro secrets set PAPER_VISION_API_KEY
paper-repro secrets set GITHUB_MCP_TOKEN
paper-repro secrets list
paper-repro config show
```

清空密钥：`paper-repro secrets clear --yes`；删除全部 paper-repro 全局配置：`paper-repro config reset --scope global --yes`。详见 [`docs/UNIFIED_CONFIG_CN.md`](docs/UNIFIED_CONFIG_CN.md)。

### 基础联网与 MCP

`paper-opencode` 默认启用 OpenCode 内建 websearch（无需搜索 API Key）和 Context7；GitHub 只读、Hugging Face 官方 MCP 与 Brave Search 备用源可按需开启。详见 [`docs/MCP_INTEGRATION_CN.md`](docs/MCP_INTEGRATION_CN.md)。

### GitHub 隐私安全开源发布

已验证的系统迭代可以生成待发布候选，并从**安装时保存的系统源码快照**创建隔离开源快照。发布流程不会读取或打包当前论文项目，上传前会扫描真实密钥及编码形式、私钥、认证文件、项目路径、PDF、日志、数据集、模型和 checkpoint；任何阻断项都会禁止上传。

```bash
paper-repro publish configure --interactive
paper-repro publish prepare
paper-repro publish review PUB-...
paper-repro publish approve PUB-...
paper-repro publish push PUB-...
```

OpenCode 中：

```text
/repro-publish
/repro-publications
```

已有仓库默认创建分支和 Pull Request，不自动合并；公开快照附带最小权限 CI、系统 Issue 表单和贡献隐私规范。详见 [`docs/GITHUB_PUBLICATION_CN.md`](docs/GITHUB_PUBLICATION_CN.md)。

## 一次性安装

```bash
conda create -n paper-repro-control python=3.11 -y
conda activate paper-repro-control
bash bootstrap.sh
```

安装内容：

- OpenCode、Node.js、`paper-repro` 控制器：控制 Conda 内；
- `/reproduce`、Agents、Tools、Plugin：当前用户的 `~/.config/opencode/`；
- `paper-opencode`、`paper-repro` 用户级启动器：默认位于 `~/.local/bin/`。

若 `~/.local/bin` 不在 PATH：

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

## 每个项目的使用方式

进入项目目录，但不需要在项目环境中重新安装 OpenCode：

```bash
cd /srv/projects/example-paper

# 新建项目执行环境；环境名完全自定义
paper-repro env create --name lead-repro-py310 --python 3.10

# 或选择已经存在的环境
paper-repro env use --name lead-repro-py310

paper-repro env show
paper-opencode --auto -m <provider>/<base-model>
```

在 OpenCode 中：

```text
/reproduce <GitHub仓库或当前仓库> <论文PDF路径或URL>
```

另一个终端查看实时状态：

```bash
cd /srv/projects/example-paper
paper-repro status --watch
```

状态页持续显示：

- 当前工作区；
- 控制 Conda 名称和 prefix；
- 项目 Conda 名称和 prefix；
- 当前步骤 `n/8` 和剩余步骤；
- 当前任务百分比、完成量、速度和 ETA；
- 总体进度、耗时、GPU 利用率和显存。

## 大文件下载

普通 HTTP/HTTPS 文件：

```bash
paper-repro download \
  --url https://example.org/model.bin \
  --output .paper-repro/cache/models/model.bin \
  --stage assets \
  --kind checkpoint
```

支持断点续传、字节进度、速度、ETA、SHA256 和自动产物登记。

## 项目内部进度协议

训练或评测程序输出：

```text
REPRO_PROGRESS 37/100 evaluating batch 37
```

控制器会同步当前任务进度和 ETA。`37/100` 必须对应真实 batch、样本、epoch 或实验组合。

## 常用命令

```bash
paper-repro env show
paper-repro env create --name <ENV> --python 3.10
paper-repro env use --name <ENV>
paper-repro doctor
paper-repro status --watch
paper-repro runs list
paper-repro issue list
paper-repro blocker list
paper-repro code index
paper-repro paper policy show
paper-repro decisions policy show
paper-repro decisions list --pending
paper-repro feedback
paper-repro publish policy show
paper-repro publish list
```

## 状态与日志位置

所有项目数据均保存在：

```text
<workspace>/.paper-repro/
├── config.json
├── current
├── cache/
├── runs/<run-id>/
└── system/
```

不会根据项目文件夹名推断环境，也不会把项目结果写入 Starter 安装目录。

## 原生优先的多模态路由

系统不绑定任何底座或备用视觉模型。所有 Agent 默认继承当前 OpenCode 底座模型；当底座能够读取图片时优先使用原生视觉能力，只有底座为纯文本或原生视觉失败时，才调用用户配置的 OpenAI-compatible 备用 profile。

```bash
paper-repro models show
paper-repro models profile set --help
paper-repro models route --help
```

详见 [`docs/MODEL_ROUTING_CN.md`](docs/MODEL_ROUTING_CN.md)。

## v0.9.0：受控自我迭代

系统功能 issue 或用户提出的 paper-repro 改进要求，可以交给 OpenCode 在隔离源码快照中分析、修改和运行回归测试：

```text
/repro-improve SYS-...
/repro-improve 希望状态页显示视觉复核页码
/repro-improvements
```

CLI：

```bash
paper-repro improve policy show
paper-repro improve list
paper-repro improve status IMP-...
```

低风险补丁可在 `guarded` 模式下自动应用；控制器、安装器、权限、密钥、MCP、Tool 和 Plugin 修改必须进入决策层。项目依赖、数据、训练和算法问题不会触发系统自改。详见 `docs/SELF_IMPROVEMENT_CN.md`。
