# OpenCode Paper Reproduction Starter

基于 **OpenCode + 可配置底座模型** 的论文代码自动复现系统：在新服务器上自动完成论文审计、环境准备、资产下载、实验执行、结果核验与报告归档。

当前版本：**2.2.1**　（完整中文手册：[`USAGE_CN.md`](USAGE_CN.md)，更新记录：[`CHANGELOG_CN.md`](CHANGELOG_CN.md)）

## 核心设计

- **OpenCode / Agent**：阅读论文与代码、制定计划、判断下一步；
- **paper-repro 控制器与 Runtime**：真正负责 Conda、下载、GPU 调度、长任务、日志、状态与安全边界。

长时间训练不依赖 OpenCode 对话持续在线，项目命令也不会误跑到系统 Python 或控制环境。

## 安装（只需一次）

```bash
conda create -n paper-repro-control python=3.11 -y
conda activate paper-repro-control
bash bootstrap.sh
```

安装内容：OpenCode、Node.js 与 `paper-repro` 控制器装入控制 Conda；`/reproduce` 等命令、Agents、Tools、Plugin 装入当前用户的 `~/.config/opencode/`；用户级启动器 `paper-opencode`、`paper-repro` 位于 `~/.local/bin/`。

> 若命令找不到：`echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc`

安装后检查：`paper-repro --version`（应为 `2.2.1`）、`paper-repro doctor`。

## 每个项目

```bash
cd /path/to/project

# 项目独立 Conda（名称随意，如 project-py310）
paper-repro env create --name project-py310 --python 3.10
# 或使用已有环境：paper-repro env use --name project-py310

paper-repro env show
paper-repro doctor
```

启动 OpenCode（先 `/connect`、`/models` 配置模型）：

```bash
paper-opencode --auto -m <provider>/<model-id>
```

OpenCode 中开始复现：

```text
/reproduce . /absolute/path/to/paper.pdf
# 或 /reproduce https://github.com/ORG/REPO /absolute/path/to/paper.pdf
```

另一终端实时查看状态：

```bash
paper-repro status --watch
```

## 8 个固定阶段

| 步骤 | 内容 | 产出 |
|---|---|---|
| 1 | 论文实验审计 | 表格、指标、数据集、实验条件清单 |
| 2 | 仓库代码审计 | 训练/评测入口、配置、功能映射 |
| 3 | 论文—代码覆盖评估 | 可复现范围 |
| 4 | 模型、数据、checkpoint 准备 | 资产清单与下载记录 |
| 5 | 项目环境与依赖 | Conda/依赖安装与环境快照 |
| 6 | 实验执行 | 训练/评测任务、GPU、日志、原始结果 |
| 7 | 结果核验 | 论文值与本次结果逐项比较 |
| 8 | 报告归档 | `report.md`、`summary.json`、问题记录 |

## 常用命令

```bash
# 环境
paper-repro env create --name ENV --python 3.10
paper-repro env use --name ENV
paper-repro env show

# 诊断 / 状态
paper-repro doctor
paper-repro status --watch        # --json 机器可读
paper-repro runs list

# GPU（每次 run 必须确认）
paper-repro gpu prepare --json
paper-repro gpu configure --ids 0,1 --max-parallel 2   # CPU-only: --ids none

# 下载
paper-repro download --url URL --output .paper-repro/cache/models/model.bin --stage assets --kind checkpoint

# 安全
paper-repro security show
paper-repro security secret allow HF_TOKEN --yes
paper-repro security download-root add /data/paper-assets --yes

# 问题反馈
paper-repro issue list --all      # 系统问题
paper-repro blocker list --all    # 项目阻塞
paper-repro feedback
```

## 决策模式

默认 `balanced`（低风险自动、中高影响询问），可用 `autonomous` / `collaborative` / `strict`，设置：

```bash
paper-repro decisions policy set --scope workspace --mode balanced
```

## 数据与安全要点

- 所有项目数据保存在 `<workspace>/.paper-repro/`，不会写入安装目录；
- 第三方论文代码默认**不继承**控制平面 Token/API Key，默认要求 Linux `bwrap` OS 沙箱，缺 `bwrap` 时 fail-closed；
- 项目环境不能与控制环境（`paper-repro-control`）相同；
- 训练程序可输出 `REPRO_PROGRESS 37/100 evaluating batch 37` 同步真实进度。

## 文档

- 完整中文手册：[`USAGE_CN.md`](USAGE_CN.md)
- 模型能力路由：[`docs/MODEL_ROUTING_CN.md`](docs/MODEL_ROUTING_CN.md)
- 执行内核：[`docs/EXECUTION_RUNTIME_V2_CN.md`](docs/EXECUTION_RUNTIME_V2_CN.md)
- 安全加固：[`docs/SECURITY_HARDENING_2.2.1_CN.md`](docs/SECURITY_HARDENING_2.2.1_CN.md)
- 其余文档见 [`docs/`](docs/) 目录。
