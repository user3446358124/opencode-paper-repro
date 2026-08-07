# 基础联网与 MCP 能力包（v0.6.0）

## 设计原则

系统不以 MCP 为中心。OpenCode 自带文件、Bash、`webfetch` 和 `websearch`；MCP 只补充结构化外部数据。`paper-opencode` 默认设置 `OPENCODE_ENABLE_EXA=1`，因此即使底座是 DeepSeek，也可使用 OpenCode 内建的 Exa 网页搜索，无需另填搜索 API Key。

默认启用：

1. OpenCode 内建 `websearch`：网页发现。
2. OpenCode 内建 `webfetch`：读取已知 URL。
3. Context7 MCP：公共库和框架文档。

按需启用：

4. GitHub 官方 MCP，只读：Release、Issue、PR、仓库元数据。
5. Hugging Face 官方 MCP：模型、数据集、论文和 Hub 文档。
6. Brave Search MCP：内建搜索不可用或需要第二搜索源时的备用。

不安装 filesystem、shell、Memory MCP，因为这些与现有工具和状态系统重复。

## 安装

覆盖安装 v0.6.0 时，`bootstrap.sh` 会创建：

```text
~/.config/paper-repro/mcp-settings.json
~/.config/paper-repro/opencode.mcp.runtime.json
```

并让 `paper-opencode` 自动加载运行配置。已有 `~/.config/opencode/opencode.json` 不会被覆盖。

```bash
PAPER_REPRO_SKIP_DEPENDENCIES=1 bash bootstrap.sh
paper-repro mcp status
```

## 管理命令

```bash
paper-repro mcp install-basic
paper-repro mcp status
paper-repro mcp recommend
paper-repro mcp enable github-readonly
paper-repro mcp enable huggingface
paper-repro mcp enable brave-search
paper-repro mcp disable <名称>
paper-repro mcp sync
```

修改后完全重启 `paper-opencode`。

## API 与认证

### 内建 websearch

无需 API Key。启动器默认：

```bash
OPENCODE_ENABLE_EXA=1
```

可临时关闭：

```bash
OPENCODE_ENABLE_EXA=0 paper-opencode
```

### Context7

匿名访问有较低限额；长期使用建议：

```bash
paper-repro secrets set CONTEXT7_API_KEY
paper-repro mcp sync
```

真实密钥只写入权限为 `600` 的统一 `~/.config/paper-repro/config.json`；生成的 MCP 运行配置只保存 `{env:CONTEXT7_API_KEY}`。

### GitHub 只读

```bash
paper-repro secrets set GITHUB_MCP_TOKEN
paper-repro mcp enable github-readonly
```

也可以不设置 Token，在 OpenCode 的 MCP 认证流程中完成 OAuth。系统同时设置 `/readonly`、`X-MCP-Readonly=true`，并只选择 `repos,issues,pull_requests`。

### Hugging Face

```bash
paper-repro secrets set HF_TOKEN
paper-repro mcp enable huggingface
```

也识别 `HUGGING_FACE_HUB_TOKEN`。URL 添加 `no_image_content=true`，避免无关图片占用上下文。默认只建议检索模型、数据集、论文与文档，不授权 Jobs、Sandboxes 或仓库写入。

### Brave Search 备用

```bash
paper-repro secrets set BRAVE_API_KEY
paper-repro mcp enable brave-search
```

仅开放 `brave_web_search`、`brave_news_search` 和 `brave_llm_context`。它不是默认搜索源。

## 推荐调用顺序

```text
发现网页/论文/项目入口 → 内建 websearch
读取已知网页          → 内建 webfetch
查依赖版本文档        → Context7
查 Issue/PR/Release    → GitHub read-only
查模型/数据集/Hub论文  → Hugging Face
交叉搜索或内建不可用   → Brave Search
```

DeepSeek Flash 的工具选择能力会因工具数量增加而下降，因此不要让所有 MCP 在每个 Agent 中同时活跃。Agent 只在任务匹配时调用一个结构化 MCP。

## 验证

```bash
paper-repro mcp status
paper-opencode
```

在 OpenCode 中：

```text
/repro-mcp
```

可测试：

```text
使用 websearch 搜索该论文的官方仓库。
使用 context7 查询 transformers 4.x 的 Trainer 参数。
使用 github-readonly 查找作者关于复现参数的 Issue。
使用 huggingface 查找 README 中引用的模型 revision。
```


统一配置、备份和清除方式见 [`UNIFIED_CONFIG_CN.md`](UNIFIED_CONFIG_CN.md)。
