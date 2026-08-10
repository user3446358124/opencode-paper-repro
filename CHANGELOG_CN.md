# v2.2.1

- 新增统一安全模块 `scripts/security.py`：项目环境密钥清洗、统一脱敏、symlink 检测。
- 项目任务默认不继承控制平面 Token/API Key；新增 workspace/task 两级显式 secret allowlist。
- 新增 bubblewrap 项目执行沙箱；`auto/required` 缺少 bwrap 时 fail-closed，`trusted-off` 必须用户 `--yes`。
- sandbox 改为最小文件系统可见性：不挂载宿主 `/`，隐藏真实 `.paper-repro` 控制状态，只暴露 cache/任务交换目录、当前 project Conda、必要系统库与显式授权数据根。
- sandbox 强制 project Conda 与 control Conda 分离；隐藏 Conda sibling env，并保护 `.git/.opencode/opencode.jsonc/AGENTS.md`。
- GitHub 公开快照递归拒绝任何 symlink，修复嵌套链接越界复制。
- 安装/卸载增加危险路径与 install marker 校验。
- 下载器增加 workspace/cache 写入边界和显式 external root 白名单。
- OpenCode read/plugin 增加 paper-repro、SSH、Git、AWS、GCloud、auth.json 敏感路径阻断，并清空 Bash 子进程中的控制凭据。
- 新建状态文件默认 user-only 权限；统一 `umask 077`。
- 新增 `security permissions repair`，可将旧 workspace/global 配置权限迁移到目录 700 / 文件 600。
- 默认固定 OpenCode、Node.js、GitHub CLI、bubblewrap 与 Python 控制依赖版本；bubblewrap 安装在 control Conda，不使用 sudo/apt。
- Brave Search MCP 固定为 2.1.0；新增 `dependency-pins.json`，并明确“直接版本固定 ≠ artifact/hash 完全锁定”。
- 新增 `paper-repro security ...`、`/repro-security` 与 `tests/security_hardening_test.py` CI gate。

# v2.2.0

- 正式冻结 **Remote Contract v1**，双方只依赖 capabilities / snapshot / events / decisions / session hint / command audit。
- `workspace_id` 改为持久化跨路径身份；旧 v2.1 工作区首次升级时沿用旧路径哈希 ID 后持久化，避免已有 Bridge cursor 失效。
- 明确 `task_id` 同 run 永不复用；`event_id` 仅在同 run 单调，event-seq 文件丢失时从日志恢复最大序号。
- `remote decide` 新增稳定 `code`、`resolved_option` / `requested_option`，重复相同选择幂等，冲突返回固定机器码。
- 远程输出时间统一规范化为 RFC3339 + 显式 timezone offset。
- GPU assignment 输出 `assignment_source`、`confidence`、`integrity`；task progress 固定 high/medium/low/unknown 真实性等级。
- Remote command audit 生命周期冻结为 queued/dispatched/accepted/completed/failed/expired/cancelled，并阻止 terminal state 被改写。
- 新增 Remote Contract v1 Schema、session/discover/decide-response Schema 与强化后的 contract test；CI 将契约测试作为独立 release gate。
- v2.1 兼容别名 `opencode_session_hint`、snapshot `task_list/gpu` 暂留至 Remote Contract v2 前。

# v2.1.0

- Remote Bridge 契约稳定化：新增 `remote capabilities --json`，客户端按 capability 而不是版本字符串判断功能。
- `remote snapshot` 对齐业务契约：顶层 pipeline、active/queued/recent task 分组、语义 `gpu_assignments`、blocker/decision 计数、OpenCode session hint。
- GPU 原始遥测从默认远程快照拆出；Bridge 正常情况下自行采集 `nvidia-smi`，诊断时使用 `--include-telemetry`。
- 明确 event cursor 为 run-scoped；`remote events` 新增 `run_id/cursor_found/next_cursor/has_more`，Bridge 应保存 `(workspace_id, run_id, event_id)`。
- `remote decide` 支持幂等：重复相同答案成功返回 `already_resolved`；不同客户端冲突时返回 conflict，不覆盖先前选择。
- research decision / blocker / stage 更新同步进入 runtime semantic event stream。
- 新增 OpenCode session/directory hint：`remote session show/bind/clear`，仅作为 Bridge 选会话的提示，不作为权威在线状态。
- 新增 `remote command record/list`，只记录 Bridge → OpenCode 写操作的脱敏审计元数据；paper-repro 不代理 OpenCode HTTP，也不保存完整 prompt。
- 新增 Remote Contract JSON Schema 与 `tests/remote_contract_test.py`。
- 文档明确：OpenCode permission/question/prompt/slash command 继续由 Bridge 直接对接当前运行实例的 OpenAPI/HTTP；paper-repro 不提供 arbitrary remote shell。

# v2.0.0

- **执行内核重构**：长任务从 OpenCode 主会话同步调用改为持久 Task Registry + 独立 Scheduler + Task Worker；`repro_exec` 现在只提交任务并立即返回 `task_id`。
- 新增每次 run 的 GPU 资源池确认：执行前列出物理 GPU、显存和占用，由用户明确允许调度的 GPU ID；未确认时 GPU 任务只排队不启动。
- 新增多 GPU 自动调度：独立单卡任务自动并行、任务完成后自动补位；多卡任务显式声明 `gpu_count`、`gpu_ids` 和 `parallel_group_id`。
- 用户确认的 GPU pool 成为硬边界；任务 affinity 不得扩展到池外 GPU；默认避开检测到的外部繁忙 GPU。
- 新增 execution plan：experiment-runner 从论文复现矩阵、仓库入口和配置生成完整任务矩阵后一次性提交，调度不再依赖 Agent 持续在线。
- 新增稳定 Task Registry：`runtime/tasks.json`、`task-specs.json`、`snapshot.json`、`remote-events.jsonl`，任务语义不再由 PID/日志反推。
- 新增 `paper-repro runtime`、`scheduler`、`gpu` 与 `remote` 命令族；远程端可 `discover → snapshot → events` 增量读取。
- 新增安全远程状态：默认隐藏命令、cwd 和 Conda prefix；远程控制仅允许 ID 化决策，不提供 arbitrary shell。
- 新增任务级 progress adapter：native `REPRO_PROGRESS`、tqdm、jsonl/line/file count、regex-log；禁止扫描整个 logs 目录猜当前任务。
- ETA 明确区分 `timeout_seconds`、`estimate_seconds` 与实时 `eta_seconds`，同时记录来源和置信度。
- 修复 `decisions --default-option undefined`；未提供默认项时优先 recommended option。
- 修复 OpenCode Tool 可选参数被序列化为字面量 `undefined` 的问题。
- OpenCode bash 直接执行 python/pip/torchrun/accelerate/deepspeed/setsid/nohup 默认拒绝，长任务必须走持久执行器。
- OpenCode 原始调试事件与 paper-repro 语义事件分流；原始事件日志支持滚动，避免长期运行后远程状态读取受大日志拖累。

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
