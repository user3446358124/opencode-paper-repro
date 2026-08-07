# v1.0.0

- 新增隐私优先的 GitHub 开源发布闭环，只从安装时保存的系统源码快照生成发布内容。
- 新增 `open-source-publisher` Agent、`/repro-publish`、`/repro-publications` 和 `repro_publish` 工具。
- 新增 `paper-repro publish configure/policy/auth/list/prepare/scan/review/approve/push/abort/purge-local`。
- GitHub owner、仓库名、可见性、简介、许可证、版权归属和更新方式在发布前集中询问；Token 禁止粘贴到聊天中。
- 支持 GitHub CLI OAuth 或统一密钥文件中的 `GITHUB_PUBLISH_TOKEN`。
- 发布快照采用顶层 allowlist，排除项目工作区、`.paper-repro`、PDF、数据、模型、checkpoint、日志、反馈包和认证文件。
- 新增真实密钥原值、Base64、URL 编码扫描，以及 GitHub/Hugging Face/AWS/通用密钥、私钥、Authorization、敏感路径、二进制、绝对路径和项目标识扫描。
- 若检测到 gitleaks，自动追加独立扫描；任一阻断项都禁止批准和推送。
- 最终批准绑定精确仓库、可见性和快照 SHA256，并设置短时有效期。
- 新仓库使用全新 Git 历史；已有仓库默认创建独立分支和 Pull Request，不自动合并。
- 不允许绕过 GitHub push protection；疑似泄漏时要求先撤销/轮换凭据。
- 自我迭代只有在真实场景 `verify --passed` 后才生成发布候选；可自动准备和扫描，但永不自动批准外部发布。
- 新增 `SECURITY.md`、`PRIVACY.md`、MIT LICENSE 和强化 `.gitignore` 到公开快照。
- 新增 `managed-mirror` / `preserve-extra` 两种已有仓库同步策略；默认使用专用镜像模式。
- 公开仓库没有许可证时隐私扫描直接阻断，避免把“可见源码”误当作开源。
- 扫描当前进程中疑似凭据环境变量，覆盖未写入统一配置的临时 Token。
- 公开快照新增最小权限 GitHub Actions CI、系统缺陷/功能建议 Issue 表单和 `CONTRIBUTING.md`。
- 新增运行策略优化：`repro_exec` 默认 `gpus="auto"` 自动选择「显存最少、利用率最低」的空闲卡并设置 `CUDA_VISIBLE_DEVICES`，并避开本 run 中仍在运行的命令已占用的 GPU（commands.jsonl 记录实际分配的 `gpus_index`）；支持 `--gpus 0,1` 显式多卡、`--gpus all/none`；默认值可由 `config.json` 的 `execution_env.gpus_default` 配置（优先级：CLI `gpus` > 配置 > auto）；命令内显式 `CUDA_VISIBLE_DEVICES=...` 时不会被覆盖；日志头、commands.jsonl 和返回 JSON 记录实际 GPU 分配说明。
- 多卡使用引导写入 experiment-runner 提示词：独立实验分卡并行传不同 `gpus`，torchrun/accelerate/deepspeed 单命令多卡时显式传 `gpus: "0,1"` 并对齐 `nproc_per_node`/`num_processes`。
- 冒烟测试新增双卡模拟：验证自动选卡、显式选卡、`none` 与命令内显式设置四种场景。

## v0.9.0

- 新增受控 OpenCode 自我迭代：系统 issue 和用户明确需求可生成隔离修复任务。
- 新增 `system-maintainer` Agent、`/repro-improve`、`/repro-improvements` 和 `repro_self` 受限工具。
- 新增 `paper-repro improve` 完整 CLI：策略、入队、隔离源码、读写、测试、差异、提案、自动应用、验证、回滚和丢弃。
- 系统 issue 默认去重进入改进候选队列；项目 blocker 永远不触发系统自改。
- 安装目录新增完整、无密钥的源码快照，Agent 不直接修改已安装系统。
- 新增 Python/Shell/JSON/smoke test/真实密钥泄漏扫描。
- 新增补丁风险分类：少量文档/提示词/测试可安全自动应用；控制器、安装器、权限、密钥、MCP、Tool 和 Plugin 修改进入决策层。
- 应用前自动保存回滚源码；应用后必须真实场景验证，才关闭来源系统 issue。

# v0.8.0

- 新增独立于 OpenCode `--auto` 的自适应人工决策层。
- 新增 `autonomous`、`balanced`、`collaborative`、`strict` 四种决策模式；默认 `balanced`。
- 按影响范围、可逆性、置信度、结果语义、外部副作用、时间、成本、下载规模和补丁范围计算 L0–L3 决策等级。
- 新增每阶段/每次运行交互预算，以及每个检查点最多 3 项的合并询问机制。
- 新增 `paper-repro decisions policy/assess/list/checkpoint/resolve` 与 `/repro-decisions`。
- 支持 workspace/global 决策偏好记忆；许可、凭据、删除、系统级和外部写入类 L3 决策永不自动通过。
- 待决策时 `repro_exec` 返回退出码 3 并暂停，不会误记为系统功能故障。
- 新增 `meta/decisions.jsonl`、`meta/decision-checkpoint.json` 和 `report/DECISIONS.md`。
- 状态页显示当前决策模式、待确认数量和高优先级决策。

# v0.7.0

- 新增单一全局配置源 `~/.config/paper-repro/config.json`，统一保存 secrets、模型路由和 MCP 开关。
- `paper-opencode` 与 `paper-repro` 启动时自动加载持久化密钥，显式 shell 环境变量优先。
- 新增 `paper-repro secrets init/set/unset/list/import-env/edit/clear`。
- 新增 `paper-repro config show/reset`，可删除全局、当前项目或全部 paper-repro 配置而不删除运行结果。
- 配置文件强制使用目录 `700`、文件 `600`，列表输出仅显示长度和短指纹。
- 自动迁移旧版 `model-routing.json`、`mcp-settings.json` 和 `secrets.json`。
- OpenCode `/connect` 的共享凭据保持独立，系统不会自动删除。

# v0.6.0

- `paper-opencode` 默认启用 OpenCode 内建 Exa websearch，无需搜索 API Key。
- 新增 MCP 基础能力包与 `mcp install-basic/status/enable/disable/sync`。
- 默认启用 Context7；GitHub 官方只读、Hugging Face 官方、Brave Search 备用按需启用。
- MCP 运行配置与用户 OpenCode 主配置分离，密钥只通过环境变量读取。
- Agent 新增按任务路由规则，避免同时加载和调用所有 MCP。

# 更新日志

## 0.5.0

- 新增 `/repro-explain` 和 code-explainer，生成整仓代码阅读手册、调用链、论文核心模块映射、数据/tensor 流和运行时证据。
- 新增 `paper-repro code index/show`，对 Python 进行 AST 静态索引并生成 Mermaid 候选调用图。
- 新增 PDF 混合审计：`paper-repro paper policy/inspect`，默认 targeted，目标表格和核心方法图强制视觉复核。
- `paper_manifest.json` 新增 extraction provenance，明确文本提取器、视觉策略、真实视觉调用次数和页码。
- 系统功能问题与项目复现阻塞完全分离：`issue`/`SYSTEM_ISSUES.md` 与 `blocker`/`RUN_BLOCKERS.md`。
- 系统反馈包默认排除项目实现问题、项目命令和运行日志。
- `status --watch` 主要字段、状态、步骤、任务和 GPU 标题中文化。
- 新增可选 MCP 模板与 `/repro-mcp`；默认禁用，推荐 Context7 和只读 GitHub MCP。

## 0.4.0

- 删除全部 Agent、Command 和默认配置中的底座模型硬编码。
- 所有代理默认继承当前 OpenCode 底座模型。
- 新增 `native-first` 能力路由：底座有视觉能力时优先原生处理。
- 新增可配置 OpenAI-compatible 备用多模态 profile 和按任务路由。
- 新增 `paper-repro models`、`paper-repro vision`、`/repro-models` 和 `repro_vision`。
- 支持将指定 PDF 页面渲染为图片后交给备用视觉 API。
- 仅保存 API Key 环境变量名称，不保存密钥值。

# 变更记录

## 0.3.0 — 2026-08-03

### 架构调整

- 将“控制 Conda”和“项目 Conda”完全分离。
- OpenCode 与 `paper-repro` 只需在固定控制环境安装一次。
- 新增用户级 `paper-opencode` 与 `paper-repro` 启动器，可从任意项目目录使用。
- 项目文件夹名不再参与 Conda 环境推断；项目环境显式写入 `.paper-repro/config.json`。

### 新增

- `paper-repro env show/use/create/clear`。
- 项目命令自动通过 `conda run -p <project-prefix>` 进入配置环境。
- 直接在错误控制环境执行 python、pip、torchrun、accelerate、deepspeed 时进行拦截。
- 固定 8 步复现流水线，状态页显示当前步骤、总步骤、已完成与剩余步骤。
- 当前任务结构：百分比、完成量、总量、单位、速度、ETA 和消息。
- HTTP/HTTPS 大文件下载器：断点续传、实时进度、速度、ETA、SHA256、日志与产物登记。
- 每次长命令的终端和日志头同时记录控制 Conda 与项目 Conda。
- `/repro-env` 命令和更完整的 `/repro-status` 输出。

### 安全

- 拒绝把 Conda base 作为项目执行环境。
- 项目执行环境与控制环境不一致时，项目运行命令必须通过 `repro_exec` 或显式 `conda run`。
- 用户级启动器安装前会备份已有同名文件。

## 0.2.0 — 2026-08-03

### 修复

- 修复 `/reproduce` 只能在 Starter 目录调用的问题。
- 修复 `reproctl.py` 以当前目录作为唯一状态根导致的 `No current run`。
- 修复 OpenCode 工具硬编码从工作区查找 `scripts/reproctl.py` 的问题。
- 修复系统 Node.js 被误用、无法保证控制层位于 Conda 的问题。

### 新增

- 用户级 OpenCode Commands、Agents、Tools、Plugins 安装。
- `paper-repro` Conda CLI。
- 项目级 `.paper-repro/` 状态目录。
- Git 根目录和祖先目录自动发现。
- 工作区注册表和 `runs list/use`。
- `doctor`、问题记录和脱敏反馈包。
