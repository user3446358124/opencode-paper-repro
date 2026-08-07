# paper-repro 受控自我迭代说明（v0.9.0）

## 1. 目标

v0.9.0 允许 paper-repro 根据运行期间记录的**系统功能 issue**，或用户明确提出的系统改进要求，调用当前 OpenCode 底座模型分析和修改 paper-repro 自身。

它不是无限制的“自动改自己”。所有修改都先发生在隔离源码副本中，必须经过回归测试、差异审查和风险分类，之后才可能应用到当前用户级安装。

## 2. 可以作为输入的问题

允许：

- `/reproduce`、全局命令、Agent、Tool 或 Plugin 没有正常加载；
- Conda 隔离、状态监控、中文显示、日志、GPU、ETA 或下载进度存在系统缺陷；
- PDF 文本/视觉路由没有按配置执行；
- MCP、统一密钥、决策治理、代码讲解或反馈包功能存在系统问题；
- 用户明确提出 paper-repro 新功能或优化要求。

禁止直接作为系统自改依据：

- 某个论文项目的依赖冲突；
- 数据、checkpoint 或许可证缺失；
- 某仓库训练/评测命令失败；
- 论文算法实现不完整；
- CUDA 扩展或项目自身代码报错。

这些问题必须继续记录为 `RUN_BLOCKERS.md`，不能为了“跑通某个项目”而修改 paper-repro 系统。

## 3. 默认策略

```bash
paper-repro improve policy show
```

默认模式为 `guarded`：

- 系统 issue 自动进入候选队列，但不会在后台自行修改；
- 用户执行 `/repro-improve` 后，OpenCode 维护代理可自动完成隔离分析、修改和测试；
- 只涉及少量文档、Agent 提示词、Command、Schema 或测试的低风险补丁，可在测试通过后自动覆盖安装；
- 控制器、安装器、权限、密钥、MCP、Plugin、Tool 或命令执行路径的修改必须进入决策层；
- 原 issue 在真实场景验证前保持未解决；
- 所有已应用修改都保留回滚源码快照。

模式：

```text
off           完全关闭
manual        只允许 CLI 手工推进
propose-only  自动分析和测试，但绝不应用
guarded       安全补丁可自动应用，中高风险等待决策
```

设置：

```bash
paper-repro improve policy set --mode guarded
paper-repro improve policy set --mode propose-only
paper-repro improve policy set --mode off
```

## 4. 从系统 issue 启动

查看系统 issue：

```bash
paper-repro issue list
paper-repro improve list
```

OpenCode 中执行：

```text
/repro-improve SYS-20260805-xxxxxx-xxxxxx
```

系统会：

1. 创建 `IMP-...` 自我迭代任务；
2. 复制当前安装保存的源码快照；
3. 初始化独立 Git 基线；
4. 让 `system-maintainer` 只通过受限 `repro_self` 工具读写隔离副本；
5. 运行 Python、Shell、JSON、密钥泄漏和完整 smoke test；
6. 生成补丁、风险报告与应用建议；
7. 按策略自动应用或生成待确认决策。

## 5. 从用户要求启动

```text
/repro-improve 希望 status --watch 的视觉调用记录使用中文并显示页码
```

这类输入的来源会标记为 `user-request`，不会伪装成运行故障。

## 6. 隔离目录

```text
~/.local/state/opencode-paper-repro/self-improve/
├── queue.jsonl
├── history.jsonl
├── sessions/
│   └── IMP-.../
│       ├── context.json
│       ├── PROMPT.md
│       ├── source/
│       ├── changes.patch
│       ├── test-results.json
│       ├── REVIEW.md
│       └── apply.log
└── backups/
    └── IMP-.../source/
```

真实密钥不会复制到源码快照。测试还会扫描统一配置中的真实 secret 值，防止它们被意外写入补丁。

## 7. CLI 管理

```bash
# 扫描未解决系统 issue 并去重入队
paper-repro improve scan

# 查看队列
paper-repro improve list

# 查看单项
paper-repro improve status IMP-...

# 准备隔离副本
paper-repro improve prepare IMP-...

# 查看上下文、文件、搜索代码
paper-repro improve context IMP-...
paper-repro improve tree IMP-...
paper-repro improve search IMP-... --pattern 'status_dict'
paper-repro improve read IMP-... --path scripts/reproctl.py --start 2950 --end 3100

# 回归测试、差异和提案
paper-repro improve test IMP-...
paper-repro improve diff IMP-... --summary
paper-repro improve propose IMP-...
paper-repro improve auto IMP-...

# 显式应用（绕过自动应用资格，但仍要求测试通过）
paper-repro improve apply IMP-... --yes

# 真实场景验证
paper-repro improve verify IMP-... --passed --note '原问题场景已恢复正常'
paper-repro improve verify IMP-... --failed --note '问题仍可复现'

# 回滚
paper-repro improve rollback IMP-... --yes

# 丢弃
paper-repro improve discard IMP-... --reason '方案偏离系统设计' --delete-session
```

## 8. 风险分类

低风险自动应用候选：

- 最多默认 3 个文件；
- 全部位于 `docs/`、`tests/`、`.opencode/agents/`、`.opencode/commands/`、`schemas/` 或少量顶层说明文档；
- 回归测试全部通过；
- 差异不涉及权限、密钥、危险命令、外部写入或 Shell 执行。

中高风险：

- `scripts/`；
- `bootstrap.sh`；
- `.opencode/tools/`；
- `.opencode/plugins/`；
- `opencode.jsonc`；
- MCP 和统一配置；
- 权限与安全边界；
- 多文件、大范围修改。

中高风险不会仅因为 `paper-opencode --auto` 就自动覆盖。

## 9. 与决策治理的关系

`--auto` 是 OpenCode 工具权限行为；`improve auto` 使用 paper-repro 自己的风险策略。

对中高风险补丁，系统在当前 run 的 `DECISIONS.md` 创建：

- 应用并备份；
- 仅查看差异；
- 丢弃提案。

用户确认后重新执行：

```bash
paper-repro improve auto IMP-...
```

## 10. 为什么不立即关闭原 issue

回归测试只能证明系统内部测试通过，无法证明原服务器、原 OpenCode 会话和原项目环境中的问题已经消失。因此应用后状态为：

```text
applied / pending-real-run
```

只有真实复现环境验证后执行 `improve verify --passed`，系统才关闭来源 issue。

## 11. OpenCode 重启要求

应用或回滚会覆盖当前 Linux 用户的全局 Agent、Command、Tool 和 Plugin。OpenCode 在启动时加载这些扩展，因此必须完全退出旧进程，再运行：

```bash
paper-opencode --auto -m <provider>/<model>
```

## 12. 边界

- 不进行后台异步修改；自我迭代发生在当前 OpenCode 会话或显式 CLI 调用中。
- 不自动创建 GitHub PR，不向外部仓库写入。
- GitHub MCP 可以用于只读查询上游 Issue、PR 和 Release，但默认不能发布补丁。
- 不允许 Agent 直接编辑已安装系统；它只能通过受限工具编辑隔离副本。
- 不保证模型第一次补丁正确，默认最多两轮自动修复。
