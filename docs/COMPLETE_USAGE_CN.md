# OpenCode 论文自动复现系统完整使用说明

**系统版本：1.0.0**  
**文档版本：1.0**  
**适用环境：Linux、远程 GPU 服务器、Conda、OpenCode TUI**  
**主要用途：论文与代码审计、环境构建、实验复现、代码讲解、系统自我迭代，以及隐私安全的 GitHub 开源发布**

> 本系统安装一次后，对当前 Linux 用户的所有项目生效。每个项目只需要配置自己的 Conda 执行环境，不需要重复安装 OpenCode 扩展。

---

## 目录

1. [五分钟快速开始](#1-五分钟快速开始)
2. [系统架构与安全边界](#2-系统架构与安全边界)
3. [新服务器首次安装](#3-新服务器首次安装)
4. [从旧版本覆盖升级](#4-从旧版本覆盖升级)
5. [OpenCode 权限与底座模型配置](#5-opencode-权限与底座模型配置)
6. [统一配置与密钥管理](#6-统一配置与密钥管理)
7. [备用视觉模型与 PDF 联合审计](#7-备用视觉模型与-pdf-联合审计)
8. [基础联网与 MCP](#8-基础联网与-mcp)
9. [每个论文项目的 Conda 与工作区配置](#9-每个论文项目的-conda-与工作区配置)
10. [自适应人工决策](#10-自适应人工决策)
11. [完整论文复现流程](#11-完整论文复现流程)
12. [实时进度、下载、GPU 与日志](#12-实时进度下载gpu-与日志)
13. [整仓代码讲解与调用链](#13-整仓代码讲解与调用链)
14. [系统问题、项目阻塞与反馈包](#14-系统问题项目阻塞与反馈包)
15. [受控自我迭代](#15-受控自我迭代)
16. [GitHub 隐私安全开源发布](#16-github-隐私安全开源发布)
17. [运行管理、恢复与常用命令](#17-运行管理恢复与常用命令)
18. [常见故障排查](#18-常见故障排查)
19. [卸载与删除配置](#19-卸载与删除配置)
20. [推荐日常操作流程](#20-推荐日常操作流程)
21. [官方参考资料](#21-官方参考资料)

---

# 1. 五分钟快速开始

## 1.1 新服务器只安装一次

```bash
unzip opencode-paper-repro-starter-v1.0.0.zip
cd opencode-paper-repro-starter

conda create -n paper-repro-control python=3.11 -y
conda activate paper-repro-control

bash bootstrap.sh

echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
hash -r
```

检查：

```bash
paper-repro --version
paper-repro doctor
which paper-opencode
which paper-repro
which gh
```

`paper-repro --version` 应显示 `1.0.0`。

## 1.2 配置底座模型

启动 OpenCode：

```bash
paper-opencode
```

在 OpenCode 中：

```text
/connect
/models
```

选择提供商、输入 API Key，再选择模型。

已知当前底座为纯文本模型时：

```bash
paper-repro models native --capability text-only --scope global
```

底座原生支持图片时：

```bash
paper-repro models native --capability vision --scope global
```

不确定时：

```bash
paper-repro models native --capability auto --scope global
```

## 1.3 配置备用视觉 API

先安全保存密钥：

```bash
paper-repro secrets set PAPER_VISION_API_KEY
```

配置一个 OpenAI-compatible 视觉模型：

```bash
paper-repro models profile set \
  --name vision-fast \
  --protocol openai-compatible \
  --base-url 'https://YOUR-ENDPOINT/v1' \
  --model 'YOUR-VISION-MODEL-ID' \
  --api-key-env PAPER_VISION_API_KEY \
  --capabilities vision,document,ocr,table,chart,formula \
  --max-tokens 8192 \
  --temperature 0 \
  --scope global

for task in vision document ocr table chart formula; do
  paper-repro models route \
    --task "$task" \
    --profile vision-fast \
    --scope global
done
```

测试：

```bash
paper-repro models show
paper-repro vision test --input /absolute/path/to/test.png --task document
```

## 1.4 每个项目只配置项目 Conda

```bash
cd /path/to/paper-project

paper-repro env create \
  --name project-repro-py310 \
  --python 3.10

paper-repro env show
paper-repro doctor
```

## 1.5 开始复现

```bash
cd /path/to/paper-project
paper-opencode --auto -m <provider>/<model-id>
```

OpenCode 中：

```text
/repro-doctor
/repro-env
/repro-models
/reproduce . /absolute/path/to/paper.pdf
```

另开终端：

```bash
cd /path/to/paper-project
paper-repro status --watch
```

---

# 2. 系统架构与安全边界

## 2.1 四层结构

```text
当前 Linux 用户
├── ~/.config/opencode/
│   ├── commands/     /reproduce、/repro-publish 等
│   ├── agents/       论文、代码、实验、维护和发布代理
│   ├── tools/        paper-repro 工具桥接
│   └── plugins/      环境隔离、危险命令拦截和审计
│
├── ~/.local/bin/
│   ├── paper-opencode
│   └── paper-repro
│
├── 固定控制 Conda
│   ├── OpenCode、Node.js、GitHub CLI
│   ├── paper-repro 控制器
│   ├── PDF、下载、日志和监控工具
│   └── 不安装具体论文项目依赖
│
└── 每个项目独立 Conda
    ├── Python、PyTorch、CUDA 用户态库
    ├── 项目依赖
    └── 训练、评测和推理程序
```

## 2.2 “全局安装”的含义

这里的全局是**当前 Linux 用户级**：

- root 安装后，对 root 用户下所有项目有效；
- 普通用户安装后，只对该用户有效；
- 其他 Linux 用户需要各自安装；
- 同一用户无需在每个项目重复运行 `bootstrap.sh`。

## 2.3 工作区名与 Conda 名无关

例如：

```text
工作区：/path/to/project
项目 Conda：lead-repro-py310
```

`example-project` 只是目录名。系统不会根据目录名猜测 Conda 环境。

## 2.4 系统不自动执行的高风险行为

默认不会自动：

- 执行 `sudo`、系统包管理或驱动安装；
- 接受模型、数据集许可证；
- 绕过 gated 模型、验证码或登录；
- 删除重要文件或强制推送；
- 改变论文核心算法或指标定义；
- 把项目源码、日志、PDF、数据或密钥上传到 GitHub。

---

# 3. 新服务器首次安装

## 3.1 安装前要求

必须具备：

- Linux shell；
- Conda；
- Git；
- 能访问 npm、PyPI、Conda Forge 和模型 API 的网络；
- 足够磁盘空间；
- 使用 GPU 时宿主机已有可用 NVIDIA 驱动。

安装器不会安装 Conda、NVIDIA 驱动或系统内核模块。

## 3.2 创建控制 Conda

```bash
conda create -n paper-repro-control python=3.11 -y
conda activate paper-repro-control
```

不允许安装到 `base`。

## 3.3 执行安装

```bash
cd /path/to/opencode-paper-repro-starter
bash bootstrap.sh
```

默认安装：

```text
$CONDA_PREFIX/bin/opencode
$CONDA_PREFIX/bin/paper-repro
$CONDA_PREFIX/bin/gh
$CONDA_PREFIX/share/opencode-paper-repro/

~/.config/opencode/commands/
~/.config/opencode/agents/
~/.config/opencode/tools/
~/.config/opencode/plugins/

~/.local/bin/paper-opencode
~/.local/bin/paper-repro
```

安装内容包括 Node.js、OpenCode、GitHub CLI、PDF 工具及控制依赖。

## 3.4 安装器常用选项

| 选项 | 作用 |
|---|---|
| `OPENCODE_VERSION=<版本>` | 指定 OpenCode npm 版本 |
| `PAPER_REPRO_SKIP_DEPENDENCIES=1` | 只覆盖控制器和扩展，不重新安装依赖 |
| `PAPER_REPRO_GLOBAL_INSTALL=0` | 不安装用户级 OpenCode 扩展 |
| `PAPER_REPRO_INSTALL_HOME=<路径>` | 自定义控制器安装目录 |
| `PAPER_REPRO_CONFIG_FILE=<路径>` | 把统一配置放到指定位置 |
| `PAPER_REPRO_USER_BIN=<路径>` | 自定义用户启动器目录 |

## 3.5 验证安装

```bash
paper-repro --version
paper-repro paths
paper-repro config show
paper-repro mcp status
paper-repro decisions policy show
paper-repro improve policy show
paper-repro publish policy show
paper-repro doctor
```

检查 OpenCode 扩展：

```bash
ls ~/.config/opencode/commands/reproduce.md
ls ~/.config/opencode/commands/repro-publish.md
ls ~/.config/opencode/agents/repro-orchestrator.md
ls ~/.config/opencode/agents/open-source-publisher.md
ls ~/.config/opencode/tools/repro.ts
ls ~/.config/opencode/plugins/repro-audit.ts
```

---

# 4. 从旧版本覆盖升级

## 4.1 推荐升级流程

先完全退出 OpenCode：

```bash
pkill -f opencode || true
```

激活原控制环境：

```bash
conda activate paper-repro-control
```

解压新版并覆盖：

```bash
unzip opencode-paper-repro-starter-v1.0.0.zip
cd opencode-paper-repro-starter

bash bootstrap.sh
hash -r
```

若控制环境已经安装可用的 `gh`，可以：

```bash
PAPER_REPRO_SKIP_DEPENDENCIES=1 bash bootstrap.sh
hash -r
```

## 4.2 升级后检查

```bash
paper-repro --version
which gh
gh --version
paper-repro doctor
paper-repro publish policy show
paper-repro publish auth status
```

升级会保留：

- `~/.config/paper-repro/config.json`；
- 视觉模型路由和 MCP 设置；
- 决策策略；
- 自我迭代和发布队列；
- 各项目 `.paper-repro/`；
- 项目 Conda；
- 历史 run、日志和报告。

安装器会备份被覆盖的用户级扩展和启动器到：

```text
~/.config/opencode/paper-repro-backup/<时间戳>/
```

---

# 5. OpenCode 权限与底座模型配置

## 5.1 权限模板

`bootstrap.sh` 不会覆盖现有的 `~/.config/opencode/opencode.json`。Starter 根目录的 `opencode.jsonc` 是推荐权限模板。

没有现有配置时：

```bash
mkdir -p ~/.config/opencode
cp opencode.jsonc ~/.config/opencode/opencode.json
```

已有配置时，先备份并只合并 `permission` 部分：

```bash
cp ~/.config/opencode/opencode.json \
  ~/.config/opencode/opencode.json.backup.$(date +%Y%m%d-%H%M%S)
```

推荐模板会阻止：

- `.env` 和凭据文件读取；
- `sudo`、`apt`、`yum`、`dnf`；
- 危险删除、磁盘写入、强制推送；
- 未经治理的外部写操作。

`paper-opencode --auto` 只会自动批准本来需要询问的工具权限，显式 `deny` 仍然生效；它也不会绕过 paper-repro 的研究决策和 GitHub 发布确认。

## 5.2 使用 OpenCode 内置提供商

```bash
paper-opencode
```

OpenCode 中：

```text
/connect
/models
```

随后启动：

```bash
paper-opencode --auto -m <provider>/<model-id>
```

模型统一使用 `provider/model-id` 格式。

## 5.3 DeepSeek 底座示例

通过 `/connect` 选择 DeepSeek 并输入 Key，再通过 `/models` 选择实际模型。

若手工配置 OpenAI-compatible 接口，官方 Base URL 示例为：

```text
https://api.deepseek.com
```

将真实模型 ID 以 OpenCode 中显示的内容为准。

纯文本底座：

```bash
paper-repro models native --capability text-only --scope global
```

## 5.4 自定义 OpenAI-compatible 底座

先保存密钥：

```bash
paper-repro secrets set MY_BASE_API_KEY
```

编辑 `~/.config/opencode/opencode.json`：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "internal-gateway": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Internal Gateway",
      "options": {
        "baseURL": "https://gateway.example.com/v1",
        "apiKey": "{env:MY_BASE_API_KEY}"
      },
      "models": {
        "coding-model": {
          "name": "Coding Model",
          "limit": {
            "context": 131072,
            "output": 8192
          }
        }
      }
    }
  }
}
```

启动：

```bash
paper-opencode --auto -m internal-gateway/coding-model
```

不要把 API Key 直接写入 JSON。

---

# 6. 统一配置与密钥管理

## 6.1 配置文件位置

```text
~/.config/paper-repro/config.json
```

目录权限为 `700`，文件权限为 `600`。配置统一保存：

- 底座、视觉和 MCP 密钥；
- 模型能力路由；
- MCP 开关；
- 人工决策策略；
- 自我迭代策略；
- GitHub 发布元数据。

这是受文件权限保护的明文 JSON，不是加密文件。

## 6.2 安全写入密钥

交互写入，内容不回显：

```bash
paper-repro secrets set PAPER_VISION_API_KEY
paper-repro secrets set GITHUB_MCP_TOKEN
paper-repro secrets set HF_TOKEN
paper-repro secrets set CONTEXT7_API_KEY
paper-repro secrets set BRAVE_API_KEY
paper-repro secrets set GITHUB_PUBLISH_TOKEN
```

查看状态但不显示真实值：

```bash
paper-repro secrets list
```

从现有环境变量导入：

```bash
paper-repro secrets import-env --known
paper-repro secrets import-env MY_BASE_API_KEY DASHSCOPE_API_KEY
```

## 6.3 删除密钥和配置

删除单项：

```bash
paper-repro secrets unset GITHUB_MCP_TOKEN
```

只清空全部密钥，保留路由和开关：

```bash
paper-repro secrets clear --yes
```

删除全部全局 paper-repro 配置：

```bash
paper-repro config reset --scope global --yes
```

删除当前项目配置但保留运行记录：

```bash
paper-repro config reset --scope workspace --yes
```

## 6.4 自定义配置位置

需要放到加密磁盘时，在安装前设置：

```bash
export PAPER_REPRO_CONFIG_FILE=/secure/paper-repro/config.json
bash bootstrap.sh
```

---

# 7. 备用视觉模型与 PDF 联合审计

## 7.1 原生优先，不按模型名硬编码

路由策略为 `native-first`：

1. 底座声明为 `vision`：优先使用当前底座原生视觉；
2. 底座声明为 `text-only`：直接使用备用视觉 profile；
3. 底座声明为 `auto`：先尝试原生视觉，失败后回退。

查看：

```bash
paper-repro models show
```

## 7.2 配置备用视觉 profile

```bash
paper-repro secrets set PAPER_VISION_API_KEY

paper-repro models profile set \
  --name vision-fast \
  --protocol openai-compatible \
  --base-url 'https://YOUR-ENDPOINT/v1' \
  --model 'YOUR-VISION-MODEL-ID' \
  --api-key-env PAPER_VISION_API_KEY \
  --capabilities vision,document,ocr,table,chart,formula \
  --max-tokens 8192 \
  --temperature 0 \
  --scope global
```

路由支持多个 profile，重复 `--profile` 表示优先级：

```bash
paper-repro models route \
  --task chart \
  --profile vision-fast \
  --profile vision-strong \
  --scope global
```

## 7.3 Qwen-VL 百炼示例

北京地域的 OpenAI-compatible Base URL 形式：

```text
https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
```

配置时 Base URL 停在 `/v1`，不要追加 `/chat/completions`，系统会自动追加。

```bash
paper-repro secrets set DASHSCOPE_API_KEY

paper-repro models profile set \
  --name vision-fast \
  --base-url 'https://YOUR_WORKSPACE_ID.cn-beijing.maas.aliyuncs.com/compatible-mode/v1' \
  --model 'YOUR-QWEN-VL-MODEL-ID' \
  --api-key-env DASHSCOPE_API_KEY \
  --capabilities vision,document,ocr,table,chart,formula \
  --temperature 0 \
  --scope global
```

模型 ID 以控制台当前可用值为准。

## 7.4 PDF 文本层与视觉层不是二选一

默认 `targeted` 策略：

- 文本层负责精确文字、数字、引用和页码；
- 视觉层负责表格结构、合并单元格、脚注、图、公式和版面关系；
- 扫描页、实验表格页和核心方法图页必须视觉复核；
- `paper_manifest.json` 必须记录真实视觉调用次数、页码和路由。

查看与设置：

```bash
paper-repro paper policy show

paper-repro paper policy set \
  --vision-policy targeted \
  --verify-tables \
  --verify-method-figures \
  --max-vision-pages 24 \
  --dpi 200
```

四种策略：

| 策略 | 行为 |
|---|---|
| `targeted` | 文本全文提取，表格、扫描页和核心图强制视觉复核 |
| `on-demand` | 仅文本缺失或有歧义时调用视觉 |
| `all-pages` | 所有页面都调用视觉，成本最高 |
| `off` | 不调用视觉，结果中必须说明 |

检查 PDF：

```bash
paper-repro paper inspect --input /absolute/path/to/paper.pdf
```

手工测试指定页：

```bash
paper-repro vision analyze \
  --input /absolute/path/to/paper.pdf \
  --pages '3,7-9' \
  --dpi 200 \
  --task table \
  --prompt '提取行、列、指标、数值、单位和脚注；不确定项使用 null。'
```

验证是否实际使用视觉：

```text
.paper-repro/current/analysis/vision/
.paper-repro/current/meta/events.jsonl
.paper-repro/current/analysis/paper_manifest.json
```

---

# 8. 基础联网与 MCP

## 8.1 默认能力

`paper-opencode` 默认启用：

- OpenCode 内建 `websearch`；
- `webfetch`；
- Context7 MCP。

查看：

```bash
paper-repro mcp status
paper-repro mcp recommend
```

## 8.2 推荐使用顺序

```text
普通网页发现         → websearch
已知网页读取         → webfetch
框架和依赖官方文档   → Context7
GitHub Release/Issue → GitHub 只读 MCP
模型与数据集检索     → Hugging Face MCP
备用搜索             → Brave Search MCP
```

## 8.3 启用 GitHub 只读 MCP

```bash
paper-repro secrets set GITHUB_MCP_TOKEN
paper-repro mcp enable github-readonly
paper-repro mcp status
```

该 MCP 只用于读取仓库、Issue 和 Pull Request，不开放写权限。

## 8.4 启用 Hugging Face MCP

```bash
paper-repro secrets set HF_TOKEN
paper-repro mcp enable huggingface
```

用于模型、数据集、论文和 Hub 文档检索。

## 8.5 启用 Brave 备用搜索

```bash
paper-repro secrets set BRAVE_API_KEY
paper-repro mcp enable brave-search
```

只有内建搜索不可用或需要第二来源时才建议开启。

## 8.6 管理命令

```bash
paper-repro mcp install-basic
paper-repro mcp status
paper-repro mcp sync
paper-repro mcp enable <服务>
paper-repro mcp disable <服务>
```

可用服务：

```text
native-websearch
context7
github-readonly
huggingface
brave-search
```

不建议默认安装 filesystem、shell 或写权限型 GitHub MCP，因为它们与 OpenCode 原生工具重复或扩大风险面。

---

# 9. 每个论文项目的 Conda 与工作区配置

## 9.1 工作区解析

```bash
cd /path/to/project
paper-repro paths
```

默认依次查找：

1. `--workspace`；
2. `REPRO_WORKSPACE`；
3. 向上查找 `.paper-repro/`；
4. Git 仓库根目录；
5. 使用 `--latest` 时最近登记的工作区。

若项目只是大仓库中的子目录，显式指定：

```bash
paper-repro --workspace /absolute/path/to/subfolder env show
```

## 9.2 创建项目 Conda

按环境名：

```bash
paper-repro env create \
  --name project-py310 \
  --python 3.10
```

按绝对 prefix：

```bash
paper-repro env create \
  --prefix /srv/conda-envs/project-py310 \
  --python 3.10
```

附加初始包：

```bash
paper-repro env create \
  --name project-py310 \
  --python 3.10 \
  --package pip \
  --package cmake
```

选择已有环境：

```bash
paper-repro env use --name project-py310
# 或
paper-repro env use --prefix /srv/conda-envs/project-py310
```

查看：

```bash
paper-repro env show
```

## 9.3 防止误跑到控制环境

项目环境未配置时，项目 Python、pip、训练和评测命令会被拒绝。

运行前会显示：

```text
工作区
控制 Conda 名称和 prefix
项目 Conda 名称和 prefix
当前 run 和步骤
```

项目命令通过：

```text
conda run --no-capture-output -p <项目环境prefix> ...
```

执行，不会直接使用控制 Conda。

---

# 10. 自适应人工决策

## 10.1 四种模式

```bash
paper-repro decisions policy show
```

| 模式 | 适用场景 |
|---|---|
| `autonomous` | 只询问高风险、许可和不可逆事项 |
| `balanced` | 默认；低风险自动，中高影响集中询问 |
| `collaborative` | 用户更多参与研究路线和实验范围 |
| `strict` | 所有具有实质影响的选择都先确认 |

设置当前项目：

```bash
paper-repro decisions policy set \
  --scope workspace \
  --mode balanced
```

## 10.2 决策等级

- **L0**：自动执行并记录，例如扫描、哈希、只读诊断；
- **L1**：自动执行并通知，例如 README 明确推荐的入口；
- **L2**：合并询问，例如完整数据还是子集、单 seed 还是多 seed；
- **L3**：强制人工确认，例如许可证、凭据权限、删除、外部写入、算法和指标语义改变。

## 10.3 控制打扰数量

默认：

```text
每阶段最多打断 2 次
每次运行最多打断 8 次
每个检查点最多展示 3 项
```

调整：

```bash
paper-repro decisions policy set \
  --scope workspace \
  --max-interruptions-per-stage 2 \
  --max-interruptions-per-run 8 \
  --max-decisions-per-checkpoint 3
```

查看和合并：

```bash
paper-repro decisions list --pending
paper-repro decisions checkpoint
```

确认并记忆偏好：

```bash
paper-repro decisions resolve DECISION_ID \
  --option OPTION_ID \
  --remember workspace \
  --note '本项目优先先跑单 seed smoke test'
```

等待决策时，系统允许只读分析，但阻止会改变项目的命令。

---

# 11. 完整论文复现流程

## 11.1 启动

```bash
cd /path/to/project
paper-opencode --auto -m <provider>/<model-id>
```

OpenCode 中：

```text
/reproduce <GitHub仓库地址或当前仓库> <论文PDF路径或URL>
```

示例：

```text
/reproduce . /srv/papers/paper.pdf --decision-mode balanced
```

## 11.2 固定八个阶段

| 步骤 | 内容 | 主要产物 |
|---:|---|---|
| 1 | 论文实验审计 | `paper_manifest.json` |
| 2 | 仓库代码审计 | `repo_manifest.json` |
| 3 | 论文—代码覆盖矩阵 | `reproduction_matrix.json` |
| 4 | 模型、数据和 checkpoint | `assets.lock.json` |
| 5 | 项目 Conda 与依赖 | 环境快照、安装日志 |
| 6 | 实验执行 | 命令日志、GPU、预测和结果 |
| 7 | 结果核验 | 表格逐项对比与误差说明 |
| 8 | 报告与问题归档 | `report.md`、`summary.json` |

## 11.3 覆盖矩阵状态

每个论文表格的行列级项目会被标记为：

```text
exact
partial
not_implemented
blocked
ambiguous
```

每项应附论文页码、代码路径、配置、入口、所需资产和证据。

## 11.4 恢复已有运行

OpenCode：

```text
/repro-resume
```

终端：

```bash
paper-repro runs list
paper-repro runs use RUN_ID
paper-repro status --watch
```

系统会验证已有产物哈希，尽量避免重复下载和覆盖成功结果。

---

# 12. 实时进度、下载、GPU 与日志

## 12.1 中文状态页

```bash
paper-repro status --watch
```

显示：

- 工作区；
- 当前 run；
- 当前步骤 `n/8` 和剩余步骤；
- 控制 Conda 与项目 Conda；
- 当前任务百分比、完成量、速度和 ETA；
- 总体进度和已运行时间；
- GPU 利用率、显存、温度和功耗；
- 系统功能问题、项目 blocker 和待确认决策数量。

机器读取：

```bash
paper-repro status --json
```

## 12.2 大文件下载

```bash
paper-repro download \
  --url https://example.org/model.bin \
  --output .paper-repro/cache/models/model.bin \
  --stage assets \
  --kind checkpoint
```

带校验：

```bash
paper-repro download \
  --url https://example.org/model.bin \
  --output .paper-repro/cache/models/model.bin \
  --sha256 EXPECTED_SHA256
```

支持断点续传、字节进度、速度、ETA、SHA256 和产物登记。

## 12.3 项目内部进度协议

训练或评测程序可输出：

```text
REPRO_PROGRESS 37/100 evaluating batch 37
```

`37/100` 必须是真实 batch、样本、epoch 或实验组合。总数未知时不要伪造百分比。

## 12.4 运行目录

```text
<workspace>/.paper-repro/runs/<run-id>/
├── meta/
│   ├── manifest.json
│   ├── state.json
│   ├── events.jsonl
│   ├── decisions.jsonl
│   ├── issues.jsonl
│   └── blockers.jsonl
├── analysis/
│   ├── paper_manifest.json
│   ├── repo_manifest.json
│   ├── reproduction_matrix.json
│   ├── code_index.json
│   └── vision/
├── assets/
│   ├── assets.lock.json
│   └── artifacts.jsonl
├── environment/
├── execution/
│   ├── commands.jsonl
│   ├── gpu.csv
│   └── logs/
├── results/
└── report/
    ├── report.md
    ├── summary.json
    ├── DECISIONS.md
    ├── RUN_BLOCKERS.md
    └── code-guide/
```

命令日志头会记录工作区、控制环境、项目环境、阶段、时间和脱敏命令。

---

# 13. 整仓代码讲解与调用链

## 13.1 生成完整阅读手册

OpenCode：

```text
/repro-explain all
```

按主题：

```text
/repro-explain overview
/repro-explain call-chain
/repro-explain paper-core
/repro-explain data-flow
/repro-explain runtime
/repro-explain module models.encoder
/repro-explain file train.py
```

## 13.2 静态索引

```bash
paper-repro code index
paper-repro code show
```

## 13.3 输出内容

```text
.paper-repro/current/report/code-guide/
├── README.md
├── STATIC_STRUCTURE.md
├── CODEBASE_OVERVIEW.md
├── CALL_CHAINS.md
├── PAPER_CORE_IMPLEMENTATION.md
├── DATA_AND_TENSOR_FLOW.md
├── CONFIG_AND_EXPERIMENTS.md
├── RUNTIME_TRACE.md
├── MODULE_INDEX.md
├── READING_ORDER.md
└── OPEN_QUESTIONS.md
```

讲解包括：

- 目录职责和推荐阅读顺序；
- 数据处理、训练、评测和推理入口；
- 从 CLI 到 `forward` 的调用链；
- 论文公式、模块、损失和代码实现对应关系；
- tensor shape、device、dtype 和梯度路径；
- 配置继承、CLI 参数、seed 和 checkpoint；
- loss、metric 和论文表格的生成链；
- 注册器、工厂、Hydra、callback 和 hook；
- 静态推断与运行时证据的区别；
- 缺失、近似、歧义和未确认事项。

重要结论应附 `path:line`。动态分派不能只依赖 AST 猜测。

---

# 14. 系统问题、项目阻塞与反馈包

## 14.1 系统功能问题

只记录 paper-repro/OpenCode 集成自身的问题：

```bash
paper-repro issue add \
  --title '状态页未显示视觉调用次数' \
  --details 'targeted 审计已完成，但状态页没有 provenance' \
  --category progress-ui \
  --expected '显示视觉页码和调用次数' \
  --optimization '增加视觉审计摘要'
```

位置：

```text
.paper-repro/system/SYSTEM_ISSUES.md
.paper-repro/system/issues.jsonl
```

管理：

```bash
paper-repro issue list --all
paper-repro issue resolve SYS-ID --resolution '修复说明'
```

## 14.2 项目复现 blocker

只记录某篇论文或仓库的问题：

```bash
paper-repro blocker add \
  --title 'checkpoint 链接失效' \
  --details 'README 地址返回 404' \
  --stage assets
```

管理：

```bash
paper-repro blocker list --all
paper-repro blocker resolve BLOCK-ID --resolution '已从作者 Release 获取'
```

项目 blocker 不会自动进入系统自我迭代。

## 14.3 脱敏反馈包

```bash
paper-repro feedback
```

默认只包含系统 issue、诊断和系统事件，不包含项目源码、训练结果和项目 blocker。

必要时增加最小元数据：

```bash
paper-repro feedback \
  --include-workspace-metadata \
  --include-run-metadata
```

只有排查控制器执行异常时才加入截断日志：

```bash
paper-repro feedback --include-logs
```

---

# 15. 受控自我迭代

## 15.1 适用范围

可触发：

- `/reproduce`、状态、日志、环境隔离等系统缺陷；
- PDF 路由、MCP、模型配置、反馈、代码讲解功能问题；
- 用户明确提出的通用系统改进。

不会触发：

- 单个项目依赖冲突；
- 数据集和 checkpoint 缺失；
- 训练算法或项目源码错误；
- 某个仓库特有问题。

## 15.2 策略

```bash
paper-repro improve policy show
```

模式：

| 模式 | 行为 |
|---|---|
| `guarded` | 默认；低风险补丁可自动应用，高风险进入决策层 |
| `propose-only` | 生成提案，不自动应用 |
| `manual` | 只在用户明确命令时推进 |
| `off` | 关闭自我迭代 |

## 15.3 启动改进

OpenCode：

```text
/repro-improve SYS-...
/repro-improve 希望状态页显示视觉复核页码
/repro-improvements
```

终端：

```bash
paper-repro improve submit \
  --title '状态页显示视觉复核页码' \
  --details '在当前步骤区域显示已调用视觉的页码' \
  --source user-request
```

## 15.4 隔离与测试

系统只修改：

```text
~/.local/state/opencode-paper-repro/self-improve/sessions/IMP-.../source/
```

不会直接编辑已安装系统或论文项目。

常用命令：

```bash
paper-repro improve list
paper-repro improve status IMP-...
paper-repro improve prepare IMP-...
paper-repro improve test IMP-...
paper-repro improve diff IMP-... --summary
paper-repro improve propose IMP-...
paper-repro improve auto IMP-...
```

显式应用：

```bash
paper-repro improve apply IMP-... --yes
```

应用后必须完全重启 OpenCode。

真实场景验证：

```bash
paper-repro improve verify IMP-... \
  --passed \
  --note '原问题场景已恢复正常'
```

回滚：

```bash
paper-repro improve rollback IMP-... --yes
```

---

# 16. GitHub 隐私安全开源发布

## 16.1 发布的对象

发布的是 **paper-repro 系统自身**，不是当前论文项目。

唯一发布源：

```text
$CONDA_PREFIX/share/opencode-paper-repro/source/
```

禁止从当前项目目录直接打包。

## 16.2 发布前会询问的信息

首次运行：

```bash
paper-repro publish configure --interactive
```

系统会询问：

1. GitHub 用户名或组织名；
2. 仓库名称；
3. `private`、`public` 或 `internal`；
4. 仓库简介；
5. 许可证；
6. 版权归属名称；
7. `gh` 或 Token 认证；
8. 已有仓库用 Pull Request 还是直接更新；
9. 同步模式；
10. 自我迭代验证后只通知还是自动准备。

推荐首次：

```text
visibility         = private
license            = MIT
existing-repo-mode = pull-request
sync-mode          = managed-mirror
after-verified     = notify
```

## 16.3 GitHub 认证

推荐 GitHub CLI：

```bash
gh auth login
paper-repro publish auth status
```

也可以使用统一密钥：

```bash
paper-repro secrets set GITHUB_PUBLISH_TOKEN
paper-repro publish configure \
  --auth-method token \
  --token-env GITHUB_PUBLISH_TOKEN
```

不要在 OpenCode 对话、命令参数或仓库 URL 中粘贴 Token。

## 16.4 非交互配置示例

```bash
paper-repro publish configure \
  --owner YOUR_GITHUB_OWNER \
  --repository opencode-paper-repro \
  --visibility private \
  --description 'Auditable OpenCode paper reproduction automation' \
  --license MIT \
  --copyright-holder 'YOUR_PUBLIC_NAME' \
  --auth-method gh \
  --existing-repo-mode pull-request \
  --sync-mode managed-mirror \
  --after-verified notify
```

## 16.5 完整发布流程

### 步骤 1：准备隔离快照

```bash
paper-repro publish prepare
```

关联已验证迭代：

```bash
paper-repro publish prepare --improvement-id IMP-...
```

得到 `PUB-...`。

### 步骤 2：隐私扫描和审查

```bash
paper-repro publish scan PUB-...
paper-repro publish review PUB-...
```

扫描包括：

- 真实密钥原值、Base64 和 URL 编码；
- GitHub、Hugging Face、AWS 和通用 Token 模式；
- Authorization、私钥和凭据文件；
- `.env`、`auth.json`、统一配置；
- Home、Conda prefix、主机名和项目路径；
- PDF、数据、模型、checkpoint、数据库和日志；
- 符号链接、未知二进制和超大文件；
- 可选 `gitleaks` 二次扫描。

任何阻断项存在时，不允许批准和上传。

### 步骤 3：精确批准

```bash
paper-repro publish approve PUB-...
```

输入：

```text
PUBLISH OWNER/REPOSITORY AS VISIBILITY
```

例如：

```text
PUBLISH alice/opencode-paper-repro AS private
```

批准绑定精确仓库、可见性、许可证、提交作者、同步策略和快照 SHA256，默认一小时有效。任何变化都会使批准失效。

扫描存在人工警告时：

```bash
paper-repro publish approve PUB-... --ack-warnings
```

### 步骤 4：上传

```bash
paper-repro publish push PUB-...
```

新仓库会创建全新 Git 历史。已有仓库默认创建更新分支和 Pull Request，不自动合并。

## 16.6 强制排除内容

```text
当前论文项目和子目录
.paper-repro/、.repro/、runs/
PDF、数据集、模型、checkpoint、预测结果
日志、诊断包和反馈包
统一配置和 OpenCode auth.json
.env、Token、私钥和凭据
Conda 环境和绝对项目路径
```

## 16.7 与自我迭代联动

只有真实验证通过后：

```bash
paper-repro improve verify IMP-... --passed
```

才按发布策略生成候选。

设置自动准备但不推送：

```bash
paper-repro publish configure --after-verified prepare
```

无论何种模式，外部 GitHub 写入始终需要最终确认。

## 16.8 OpenCode 发布命令

```text
/repro-publish
/repro-publish status
/repro-publish prepare IMP-...
/repro-publish review PUB-...
/repro-publish publish PUB-...
/repro-publications
```

## 16.9 发布会话位置

```text
~/.local/state/opencode-paper-repro/publish/sessions/PUB-.../
├── snapshot/
├── PUBLISH_MANIFEST.json
├── SANITIZATION.json
├── PRIVACY_SCAN.json
├── REVIEW.md
└── APPROVAL.json
```

会话目录本身不会上传。

---

# 17. 运行管理、恢复与常用命令

## 17.1 OpenCode 命令

| 命令 | 用途 |
|---|---|
| `/reproduce` | 开始全新复现 |
| `/repro-status` | 中文状态摘要 |
| `/repro-resume` | 从当前检查点继续 |
| `/repro-env` | 查看或配置项目 Conda |
| `/repro-models` | 查看模型能力路由 |
| `/repro-paper` | 查看 PDF 文本/视觉策略 |
| `/repro-explain` | 生成代码阅读手册 |
| `/repro-decisions` | 查看或调整人工决策 |
| `/repro-mcp` | 查看或管理 MCP |
| `/repro-issues` | 区分系统 issue 和项目 blocker |
| `/repro-feedback` | 生成系统反馈包 |
| `/repro-improve` | 启动系统自我迭代 |
| `/repro-improvements` | 查看自我迭代队列 |
| `/repro-publish` | 配置和执行安全开源发布 |
| `/repro-publications` | 查看发布任务 |
| `/repro-doctor` | 系统诊断 |

## 17.2 CLI 速查

```bash
paper-repro env show
paper-repro env create --name ENV --python 3.10
paper-repro env use --name ENV

paper-repro models show
paper-repro models native --capability auto
paper-repro models profile set --help
paper-repro models route --help

paper-repro paper policy show
paper-repro paper inspect --input paper.pdf
paper-repro code index

paper-repro decisions policy show
paper-repro decisions list --pending

paper-repro status --watch
paper-repro runs list
paper-repro runs use RUN_ID

paper-repro issue list --all
paper-repro blocker list --all
paper-repro feedback

paper-repro improve policy show
paper-repro improve list

paper-repro publish policy show
paper-repro publish list
paper-repro publish auth status
```

全局参数：

```bash
paper-repro --workspace /path/to/project <command>
paper-repro --state-root /custom/state <command>
paper-repro --latest <command>
```

---

# 18. 常见故障排查

## 18.1 `/reproduce` 不显示

```bash
ls ~/.config/opencode/commands/reproduce.md
which paper-opencode
pkill -f opencode || true
paper-opencode
```

检查最终配置：

```bash
paper-opencode debug config
```

## 18.2 `No current run. Call init first.`

尚未开始复现，或工作区不正确：

```bash
paper-repro paths
paper-repro runs list
paper-repro --workspace /absolute/path/to/project status --watch
```

旧状态迁移：

```bash
paper-repro migrate-legacy
```

## 18.3 `PROJECT CONDA: NOT CONFIGURED`

```bash
paper-repro env create --name project-py310 --python 3.10
# 或
paper-repro env use --name existing-env
```

## 18.4 视觉 API 404

检查：

- Base URL 是否停在 `/v1`；
- 是否错误地重复追加 `/chat/completions`；
- Workspace ID、地域和模型 ID 是否一致；
- 供应商是否支持 Chat Completions 和 Base64 Data URL。

## 18.5 视觉 API 401/403

检查：

```bash
paper-repro secrets list
paper-repro models show
```

确认 Key 权限、区域、IP 白名单和模型服务开通状态。

## 18.6 PDF 表格识别不准

```bash
paper-repro vision analyze \
  --input paper.pdf \
  --pages 7 \
  --dpi 240 \
  --task table \
  --prompt '逐单元格提取，保留单位和脚注。'
```

并与文本层、图注和正文交叉验证。

## 18.7 训练没有百分比

外部包装器不能可靠猜测任意训练脚本总 batch 数。保留项目 `tqdm`，或增加：

```text
REPRO_PROGRESS current/total message
```

## 18.8 GitHub 发布被阻断

查看：

```bash
paper-repro publish review PUB-...
```

不要绕过扫描或 GitHub push protection。先删除敏感内容、轮换疑似泄漏凭据，再重新 `prepare`。

## 18.9 GitHub CLI 不可用

```bash
which gh
gh --version
```

控制环境安装：

```bash
conda activate paper-repro-control
conda install -y -c conda-forge gh
```

## 18.10 应用自我迭代后命令未变化

完全重启 OpenCode：

```bash
pkill -f opencode || true
paper-opencode --auto -m <provider>/<model-id>
```

---

# 19. 卸载与删除配置

## 19.1 卸载系统控制层

```bash
conda activate paper-repro-control
cd /path/to/opencode-paper-repro-starter
bash scripts/uninstall.sh
```

卸载会删除控制器、启动器和本系统安装的 OpenCode 扩展，但不会删除项目 `.paper-repro/`、项目 Conda、自我迭代历史和发布历史。

## 19.2 删除自我迭代和发布本地数据

```bash
rm -rf ~/.local/state/opencode-paper-repro/self-improve
paper-repro publish purge-local --yes
```

## 19.3 删除 GitHub 认证

统一 Token：

```bash
paper-repro secrets unset GITHUB_PUBLISH_TOKEN
```

GitHub CLI：

```bash
gh auth logout --hostname github.com
```

## 19.4 删除远程仓库

系统不提供自动删除 GitHub 远程仓库。远程删除属于高风险外部操作，应由用户在 GitHub 中手工完成。

---

# 20. 推荐日常操作流程

## 20.1 首次安装日

```bash
conda create -n paper-repro-control python=3.11 -y
conda activate paper-repro-control
bash bootstrap.sh
paper-repro doctor
paper-repro secrets init
paper-repro mcp status
```

完成底座和视觉 API 配置后，运行一次视觉测试。

## 20.2 每个新论文项目

```bash
cd /path/to/project
paper-repro env create --name project-py310 --python 3.10
paper-repro env show
paper-repro doctor
paper-opencode --auto -m <provider>/<model-id>
```

OpenCode：

```text
/reproduce . /absolute/path/to/paper.pdf --decision-mode balanced
```

## 20.3 复现过程中

```bash
paper-repro status --watch
paper-repro decisions list --pending
paper-repro blocker list --all
```

必要时：

```text
/repro-explain all
/repro-paper /absolute/path/to/paper.pdf
```

## 20.4 发现系统功能问题

```bash
paper-repro issue add ...
```

OpenCode：

```text
/repro-improve SYS-...
```

测试、审查、应用，再真实验证。

## 20.5 将验证后的系统开源

```bash
paper-repro publish configure --interactive
gh auth login
paper-repro publish prepare --improvement-id IMP-...
paper-repro publish review PUB-...
paper-repro publish approve PUB-...
paper-repro publish push PUB-...
```

第一次建议使用私有仓库；确认 GitHub 页面内容后再决定是否公开。

---

# 21. 官方参考资料

以下链接用于核对 OpenCode、模型 API 与 GitHub 安全行为：

- OpenCode Providers：<https://opencode.ai/docs/providers>
- OpenCode Models：<https://opencode.ai/docs/models>
- OpenCode Permissions：<https://opencode.ai/docs/permissions>
- OpenCode Tools：<https://opencode.ai/docs/tools>
- OpenCode MCP：<https://opencode.ai/docs/mcp-servers>
- DeepSeek API：<https://api-docs.deepseek.com/>
- Qwen-VL OpenAI-compatible API：<https://help.aliyun.com/zh/model-studio/qwen-vl-compatible-with-openai>
- GitHub CLI 认证：<https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github>
- GitHub Fine-grained PAT：<https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens>
- GitHub Push Protection：<https://docs.github.com/en/code-security/concepts/secret-security/push-protection>

---

## 最终检查清单

### 安装

- [ ] 控制环境不是 `base`；
- [ ] `paper-repro --version` 为 `1.0.0`；
- [ ] `paper-opencode`、`paper-repro`、`gh` 可用；
- [ ] OpenCode 权限模板已合并；
- [ ] `/reproduce` 和 `/repro-publish` 可见。

### 配置

- [ ] 底座模型可用；
- [ ] 底座视觉能力声明正确；
- [ ] 备用视觉 profile 测试成功；
- [ ] 密钥只保存在统一配置或 OpenCode auth 中；
- [ ] MCP 只启用了必要服务。

### 项目

- [ ] 工作区路径正确；
- [ ] 项目 Conda 已显式配置；
- [ ] `paper-repro doctor` 无关键失败；
- [ ] PDF 审计策略符合预算与准确性要求；
- [ ] 决策模式符合当前项目需求。

### 发布

- [ ] 发布源是系统源码快照，不是项目目录；
- [ ] 隐私扫描为通过；
- [ ] 仓库、可见性和许可证经过人工确认；
- [ ] Token 未出现在聊天、命令行或日志；
- [ ] 已有仓库默认使用 Pull Request；
- [ ] 公共仓库包含明确许可证。
