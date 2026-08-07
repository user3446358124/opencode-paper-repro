# 统一配置与密钥管理（v0.7.0）

## 目标

v0.7.0 将当前 Linux 用户的 paper-repro 全局配置统一到一个文件：

```text
~/.config/paper-repro/config.json
```

该文件默认权限为 `600`，其目录默认权限为 `700`。它同时保存：

- `secrets`：底座模型、备用视觉模型和 MCP 使用的 API Key/Token；
- `model_routing`：原生视觉能力声明、备用视觉 API Base URL、模型 ID、能力标签和任务路由；
- `mcp`：Context7、GitHub、Hugging Face、Brave Search 等能力的启停设置。

OpenCode 使用的 MCP 运行文件：

```text
~/.config/paper-repro/opencode.mcp.runtime.json
```

只是可再生缓存，其中只出现 `{env:变量名}`，不会写入真实 Token。

## 初始化

覆盖安装 v0.7.0 后会自动创建空配置。也可以手工执行：

```bash
paper-repro secrets init
paper-repro config show
```

## 安全地写入密钥

推荐使用交互输入，密钥不会回显，也不会进入 shell 历史：

```bash
paper-repro secrets set PAPER_VISION_API_KEY
paper-repro secrets set GITHUB_MCP_TOKEN
paper-repro secrets set HF_TOKEN
paper-repro secrets set CONTEXT7_API_KEY
paper-repro secrets set BRAVE_API_KEY
```

也可以从标准输入写入：

```bash
printf '%s' "$TOKEN" | paper-repro secrets set GITHUB_MCP_TOKEN --stdin
```

`--value` 仅适合临时测试，因为值可能保留在 shell 历史或进程列表中：

```bash
paper-repro secrets set NAME --value 'value'
```

系统不限制具体供应商。任何符合大写环境变量格式的名称都可以保存，例如：

```bash
paper-repro secrets set MY_BASE_MODEL_API_KEY
paper-repro secrets set COMPANY_VISION_TOKEN
```

随后在 OpenCode Provider 或视觉 profile 中引用相同变量名。

## 查看状态但不泄露密钥

```bash
paper-repro secrets list
```

输出只包含：

- 变量名称；
- 是否已配置；
- 字符长度；
- SHA256 短指纹；
- 当前进程是否已加载。

真实值不会打印。

## 直接编辑统一文件

```bash
paper-repro secrets edit
```

默认使用 `$VISUAL`、`$EDITOR` 或 `vi`。保存后系统会验证 JSON，并重新收紧到 `600` 权限。

文件结构示例：

```json
{
  "schema_version": 1,
  "updated_at": "2026-08-04T00:00:00+00:00",
  "secrets": {
    "PAPER_VISION_API_KEY": "替换为真实值",
    "GITHUB_MCP_TOKEN": "替换为真实值"
  },
  "model_routing": {
    "policy": "native-first",
    "native": {"capability": "text-only"},
    "profiles": {
      "vision-fast": {
        "protocol": "openai-compatible",
        "base_url": "https://example.com/compatible-mode/v1",
        "model": "your-vision-model-id",
        "api_key_env": "PAPER_VISION_API_KEY",
        "capabilities": ["vision", "document", "ocr", "table", "chart", "formula"],
        "enabled": true
      }
    },
    "routes": {
      "vision": ["vision-fast"],
      "document": ["vision-fast"],
      "ocr": ["vision-fast"],
      "table": ["vision-fast"],
      "chart": ["vision-fast"],
      "formula": ["vision-fast"]
    }
  },
  "mcp": {
    "native_websearch": true,
    "servers": {
      "context7": {"enabled": true},
      "github-readonly": {"enabled": true},
      "huggingface": {"enabled": true},
      "brave-search": {"enabled": false}
    }
  }
}
```

更推荐使用 CLI 修改配置，避免手工编辑 JSON 出错。

## 配置视觉 API

先保存密钥：

```bash
paper-repro secrets set PAPER_VISION_API_KEY
```

再保存非敏感接口配置：

```bash
paper-repro models native --capability text-only

paper-repro models profile set \
  --name vision-fast \
  --protocol openai-compatible \
  --base-url 'https://YOUR-ENDPOINT/v1' \
  --model 'YOUR-VISION-MODEL-ID' \
  --api-key-env PAPER_VISION_API_KEY \
  --capabilities vision,document,ocr,table,chart,formula

paper-repro models route --task vision --profile vision-fast
paper-repro models route --task document --profile vision-fast
paper-repro models route --task table --profile vision-fast
paper-repro models route --task chart --profile vision-fast
```

以上内容全部进入同一个 `config.json`。

## 配置 MCP Token

```bash
paper-repro secrets set CONTEXT7_API_KEY
paper-repro secrets set GITHUB_MCP_TOKEN
paper-repro secrets set HF_TOKEN
paper-repro secrets set BRAVE_API_KEY

paper-repro mcp enable github-readonly
paper-repro mcp enable huggingface
paper-repro mcp enable brave-search
paper-repro mcp status
```

`paper-opencode` 每次启动都会：

1. 读取统一配置；
2. 把 `secrets` 安全注入 OpenCode 进程环境；
3. 根据 `mcp` 设置重新生成 MCP 运行缓存；
4. 启动 OpenCode。

因此不需要再把 Token 写入 `.bashrc`、`.env` 或 Conda 激活脚本。

## 导入旧环境变量

升级前已经通过 `export` 或 Conda 激活脚本设置 Token 时，可以一次性导入：

```bash
paper-repro secrets import-env --known
```

或者只导入指定变量：

```bash
paper-repro secrets import-env DASHSCOPE_API_KEY GITHUB_MCP_TOKEN HF_TOKEN
```

导入后可从旧的 shell 初始化文件中删除对应 `export`。

## 删除单项

```bash
paper-repro secrets unset GITHUB_MCP_TOKEN
```

## 清空全部密钥但保留模型/MCP设置

```bash
paper-repro secrets clear --yes
```

该命令保留视觉 endpoint、模型 ID、路由和 MCP 开关，只删除 `secrets`。

## 删除全部 paper-repro 全局配置

```bash
paper-repro config reset --scope global --yes
```

会删除：

- 统一 `config.json`；
- 生成的 MCP 运行缓存；
- 旧版本遗留的 `secrets.json`、`model-routing.json` 和 `mcp-settings.json`。

不会删除：

- 项目的 `.paper-repro/runs/`、日志和结果；
- 项目 Conda 环境；
- OpenCode 安装与扩展；
- OpenCode `/connect` 保存的共享凭据。

删除当前项目的执行环境选择、PDF 策略和项目级模型覆盖：

```bash
cd /path/to/project
paper-repro config reset --scope workspace --yes
```

同时删除全局与当前项目配置：

```bash
paper-repro config reset --scope all --yes
```

OpenCode `/connect` 的凭据位于：

```text
~/.local/share/opencode/auth.json
```

它可能包含其他 OpenCode 用途的 Provider 凭据，因此 paper-repro 永不自动删除。确认不再需要所有 OpenCode `/connect` 凭据时，才手工备份并删除该文件。

## 备份与迁移

只需备份一个源文件：

```bash
cp ~/.config/paper-repro/config.json /secure/backup/paper-repro-config.json
chmod 600 /secure/backup/paper-repro-config.json
```

恢复：

```bash
mkdir -p ~/.config/paper-repro
chmod 700 ~/.config/paper-repro
cp /secure/backup/paper-repro-config.json ~/.config/paper-repro/config.json
chmod 600 ~/.config/paper-repro/config.json
paper-repro mcp sync
```

该文件包含明文密钥。不要上传到 Git、聊天、问题反馈包或公共网盘。需要更高等级保护时，可把 `PAPER_REPRO_CONFIG_FILE` 指向加密磁盘或受控挂载目录。
