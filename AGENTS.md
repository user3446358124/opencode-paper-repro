# Paper Reproduction Rules

1. 当前 OpenCode 工作区只是目标项目路径；文件夹名不得自动视为 Conda 环境名。
2. 控制 Conda 运行 OpenCode/paper-repro；项目 Conda 运行论文代码。每个项目在 `.paper-repro/config.json` 中独立配置项目 Conda。
3. 所有 Python、pip、训练、评测和编译命令必须通过 `repro_exec`，不得直接落入控制环境或 base。
4. 先审计，后安装；先形成论文清单、代码清单和复现矩阵，再运行训练或评测。
5. 不把代码中出现某个指标名视为可以复现论文表格。必须找到入口、配置、数据路径、模型权重、评测实现和输出字段。
6. 每项结论必须带证据：论文页码或表格编号、代码文件与行号、实际命令与输出文件。
7. PDF 默认使用混合审计：文本层负责精确文字与数值，视觉层负责版面、表格关系、图和公式。targeted 策略下目标表格和核心方法图必须视觉复核，并记录真实 provenance。
8. 任何下载必须记录来源、版本或 commit/revision、许可证状态、文件大小和 SHA256。普通 HTTP 大文件优先使用 `repro_download`。
9. 流程固定为 8 步；每步通过 `repro_stage` 写入 step/step_total/step_status。程序可输出 `REPRO_PROGRESS current/total message` 更新任务进度。
10. 不修改原始仓库代码，除非已记录补丁并解释必要性。优先使用适配脚本和配置。
11. 结果分为 exact、partial、blocked、not_implemented、failed、unverified，不得使用模糊的“基本复现”。
12. 失败最多自动修复两轮；之后保存现场。项目依赖、数据、模型和实验问题调用 `repro_blocker`；paper-repro/OpenCode 功能异常或优化建议才调用 `repro_issue`。
13. 代码讲解必须区分静态候选调用链与运行时已验证调用链；重要结论给出 `path:line`，动态注册和框架隐式调用不得凭空确定。
14. 绝不记录密钥、令牌、Cookie 或 `.env` 内容。
15. 最终报告必须呈现成功项、偏差项、不可复现项、人为修改项、环境信息和未解决项目阻塞。
16. 模型路由必须按能力而非品牌：当前底座具有视觉能力时优先原生处理；只有能力缺失时才能调用 `repro_vision`。供应商、模型、Base URL 与密钥环境变量只能来自用户配置，禁止写死。
17. 联网能力优先级：OpenCode 内建 websearch/webfetch → Context7 → GitHub 只读 → Hugging Face；Brave Search 仅作备用。filesystem/shell/Memory MCP 不启用。外部结果必须保留来源，不能覆盖本地代码和真实运行证据。
18. OpenCode `--auto` 只表示工具权限自动批准，不代表研究决策自动批准。开始复现时读取 decision policy；低风险可逆选择自动记录，影响实验语义、成本、许可、外部状态或不可逆性的选择必须通过 `repro_decision` 评估。相关问题合并询问并遵守交互预算；待确认决策存在时不得绕过 `repro_exec`。

## 系统自我迭代边界

- 系统 issue 与项目 blocker 必须严格分离。
- 只有 paper-repro/OpenCode 集成本身的功能缺陷或用户明确系统改进要求，才可启动 `system-maintainer`。
- 所有系统自改必须通过 `repro_self` 在隔离源码快照中完成，禁止直接编辑已安装系统。
- 测试、风险审查、备份和真实场景验证不可跳过。
- 项目训练错误不得通过降低安全性、改变论文语义或放宽成功标准来“修复”。

## GitHub 开源发布边界

- 只有 `open-source-publisher` 可以编排 GitHub 发布。
- 发布源必须是 `$PAPER_REPRO_SOURCE_HOME` 的隔离 allowlist 快照，禁止使用当前项目工作区。
- `GITHUB_PUBLISH_TOKEN` 只能通过统一 secrets 文件或 GitHub CLI 认证进入子进程，不得写入命令、日志、Agent 输出或公开快照。
- 仓库 owner/name、visibility、license、copyright holder 和更新方式必须由用户明确提供。
- 上传前必须完成本地隐私扫描、人工 review 和绑定 manifest SHA256 的精确确认。
- 新仓库可以首次推送；已有仓库默认创建 Pull Request。不得自动合并，不得绕过 push protection，不得自动删除远程仓库。
