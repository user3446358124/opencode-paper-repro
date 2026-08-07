# GitHub 隐私安全开源发布

版本：1.0.0

本功能用于把 **paper-repro 系统本身** 的已验证版本发布到用户自己的 GitHub 仓库。发布源永远不是当前论文项目目录，而是安装时保存的无用户数据系统源码快照。

## 1. 安全边界

发布流程只允许包含：

- `scripts/`、`schemas/`、`docs/`、`configs/`；
- `.opencode/agents`、`.opencode/commands`、`.opencode/tools`、`.opencode/plugins`；
- `bootstrap.sh`、README、使用手册、测试和版本文件；
- 自动生成的 `LICENSE`、`SECURITY.md`、`PRIVACY.md`。

强制排除并阻断：

- 当前论文代码仓库和任何项目子目录；
- `.paper-repro/`、`.repro/`、runs、日志、诊断包和反馈包；
- PDF、数据集、模型、checkpoint、预测结果、W&B 文件；
- `~/.config/paper-repro/config.json`、OpenCode `auth.json`、`.env`；
- API Key、PAT、Token、密码、私钥及其 Base64/URL 编码形式；
- 当前用户 Home、服务器主机名、已登记工作区绝对路径和项目标识。

## 2. 发布策略

查看：

```bash
paper-repro publish policy show
```

默认策略：

- 发布模式：`review`；
- 自我迭代真实验证后：只生成待发布通知；
- 新仓库首次发布：推送默认分支；
- 已有仓库更新：创建独立分支和 Pull Request，不自动合并；
- 上传前必须通过隐私扫描并输入精确确认短语；
- GitHub push protection 阻断时绝不提供绕过选项。

## 3. 需要向用户询问的信息

这些信息会公开或用于仓库管理，因此必须由用户明确提供：

1. GitHub 用户名或组织名；
2. 仓库名称；
3. 可见性：`private`、`public` 或 `internal`；
4. 仓库简介；
5. 许可证：当前自动生成支持 `MIT` 或 `none`；
6. MIT 版权归属名称；
7. 认证方式：`gh` 或 `token`；
8. 已有仓库更新方式：`pull-request` 或 `direct`；
9. Git 提交作者名称和邮箱（可选，默认使用 GitHub noreply 风格地址）。

交互配置：

```bash
paper-repro publish configure --interactive
```

非交互配置示例：

```bash
paper-repro publish configure \
  --owner YOUR_GITHUB_OWNER \
  --repository opencode-paper-repro \
  --visibility private \
  --description "Auditable OpenCode paper reproduction automation" \
  --license MIT \
  --copyright-holder "YOUR_PUBLIC_NAME" \
  --auth-method gh \
  --existing-repo-mode pull-request \
  --after-verified notify
```

建议首次先发布到 private 仓库完成一次 GitHub 页面复核，再由用户主动决定是否改为 public。

## 4. GitHub 认证

### 4.1 推荐：GitHub CLI OAuth

```bash
gh auth login
paper-repro publish auth status
```

Token 不进入 paper-repro 配置，也不应粘贴到 OpenCode 对话。

### 4.2 统一密钥文件中的发布 Token

```bash
paper-repro secrets set GITHUB_PUBLISH_TOKEN
paper-repro publish configure --auth-method token --token-env GITHUB_PUBLISH_TOKEN
paper-repro publish auth status
```

输入过程隐藏，真实值保存在权限为 `600` 的：

```text
~/.config/paper-repro/config.json
```

使用 fine-grained PAT，并只授予目标仓库所需的最小权限。创建仓库和向已有仓库写入的权限需求不同；无法确认时优先使用 `gh auth login`。

## 5. 准备隔离快照

```bash
paper-repro publish prepare
```

关联某次已验证自我迭代：

```bash
paper-repro publish prepare --improvement-id IMP-...
```

输出 publication ID，例如：

```text
PUB-20260805-123000-abcdef
```

本地会话位于：

```text
~/.local/state/opencode-paper-repro/publish/sessions/PUB-.../
├── snapshot/               # 唯一可能上传的系统源码快照
├── PUBLISH_MANIFEST.json   # 文件清单与 SHA256
├── SANITIZATION.json       # 本机/项目标识替换记录
├── PRIVACY_SCAN.json       # 隐私扫描结果
├── REVIEW.md               # 人工审查摘要
└── APPROVAL.json           # 短时有效的最终批准
```

该会话目录本身不会上传。

## 6. 隐私扫描

`prepare` 默认自动扫描；也可以重跑：

```bash
paper-repro publish scan PUB-...
paper-repro publish review PUB-...
```

扫描包括：

- 统一配置及当前 `paper-repro` 进程中疑似凭据环境变量的原值、Base64 和 URL 编码；
- GitHub、Hugging Face、AWS、通用 `sk-`、Authorization 和私钥模式；
- `.env`、auth、credentials、密钥文件名；
- PDF、模型、数据、checkpoint 和数据库扩展名；
- 符号链接、未知二进制和超大文件；
- Home、Conda prefix、安装路径、主机名和工作区路径；
- 非示例邮箱和私网 IP（作为人工警告）；
- 若系统检测到 `gitleaks`，自动追加独立扫描。

任意阻断项存在时：

```text
scan.passed = false
status = blocked
```

此时 `approve` 和 `push` 都会拒绝执行。

## 7. 最终批准

审查通过后：

```bash
paper-repro publish approve PUB-...
```

系统会要求输入完整短语：

```text
PUBLISH OWNER/REPOSITORY AS VISIBILITY
```

示例：

```text
PUBLISH alice/opencode-paper-repro AS public
```

批准与以下内容绑定：

- 精确 owner/repository；
- 精确 visibility；
- 当前快照 manifest SHA256；
- 一小时有效期（默认）。

任何快照、仓库、可见性、许可证、简介、提交作者或同步策略变化都会使批准失效。若扫描存在人工警告，必须在 review 后明确使用 `--ack-warnings` 才能批准。

## 8. 上传

```bash
paper-repro publish push PUB-...
```

新仓库：

- 创建仓库；
- 克隆空仓库；
- 再次扫描最终提交树；
- 生成一个全新 Git 历史；
- 提交并推送默认分支。

已有仓库默认：

- 克隆默认分支；
- 创建 `paper-repro/update-v<version>-<timestamp>`；
- 用当前隔离快照同步系统源码；
- 再次扫描；
- 推送分支；
- 创建 Pull Request；
- 不自动合并。

`managed-mirror` 只保证本次提交树由安全快照管理，不会重写已有仓库的历史。目标仓库应当是专用于 paper-repro 的干净仓库；若历史中曾提交过凭据，必须先撤销/轮换并按 GitHub 官方流程清理历史。

系统会尝试启用 secret scanning 和 push protection；权限或套餐不支持时会记录警告，但本地隐私扫描仍然是强制门禁。

## 9. 公开仓库自带的维护设施

安全快照还包含：

- `.github/workflows/ci.yml`：只授予 `contents: read`，运行语法检查、JSON 校验和隔离 smoke test；不读取 GitHub Secrets。
- `.github/ISSUE_TEMPLATE/system-bug.yml`：只接受系统功能缺陷，并要求提交者确认不含项目材料或凭据。
- `.github/ISSUE_TEMPLATE/feature-request.yml`：收集通用功能建议。
- `CONTRIBUTING.md`：规定隐私边界和最低回归测试。

公开 GitHub Issue **不会直接自动修改系统**。后续仍需由本地 GitHub 只读 MCP 拉取、分类并进入现有受控自我迭代队列，避免远程文本直接获得执行能力。

## 10. 与自我迭代联动

只有：

```bash
paper-repro improve verify IMP-... --passed
```

完成真实场景验证后，才会按 `after_verified` 生成发布候选：

- `off`：不生成；
- `notify`：生成待配置/待准备候选；
- `prepare`：在 GitHub 元数据已完整配置时自动准备并扫描，但不会批准或推送。

设置：

```bash
paper-repro publish configure --after-verified prepare
```

无论何种模式，外部 GitHub 写入永远需要用户最终确认。

## 11. OpenCode 命令

```text
/repro-publish
/repro-publish status
/repro-publish prepare IMP-...
/repro-publish review PUB-...
/repro-publish publish PUB-...
/repro-publications
```

发布代理会合并询问公开元数据，不要求用户在聊天中粘贴 Token。

## 12. 删除本地配置和发布数据

删除统一配置中的发布 Token：

```bash
paper-repro secrets unset GITHUB_PUBLISH_TOKEN
```

若使用 GitHub CLI OAuth，退出并删除本机 `gh` 凭据：

```bash
gh auth logout --hostname github.com
```

删除全部 paper-repro 全局配置（含 GitHub 发布元数据和密钥）：

```bash
paper-repro config reset --scope global --yes
```

删除本地发布队列、快照、扫描报告和历史：

```bash
paper-repro publish purge-local --yes
```

这不会删除 GitHub 远程仓库。远程删除属于高风险外部操作，本系统不提供自动删除命令。

## 13. 凭据疑似泄漏时

1. 立即停止发布；
2. 撤销或轮换凭据；
3. 不要绕过 GitHub push protection；
4. 删除本地发布会话并重新准备；
5. 如果已经推送，先轮换凭据，再按 GitHub 官方敏感数据清理流程处理历史；
6. 重新扫描和人工审查。
