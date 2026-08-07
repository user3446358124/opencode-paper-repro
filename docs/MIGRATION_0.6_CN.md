> 本页是 v0.6.0 历史说明。v0.7.0 起请使用 `paper-repro secrets set` 和统一 `~/.config/paper-repro/config.json`。

# v0.6.0 覆盖升级说明

```bash
# 1. 退出全部 OpenCode 进程
conda activate <paper-repro 控制环境>
cd /path/to/opencode-paper-repro-starter-v0.6.0
PAPER_REPRO_SKIP_DEPENDENCIES=1 bash bootstrap.sh
hash -r

# 2. 检查基础联网能力
paper-repro mcp status

# 3. 按需配置凭据
export GITHUB_MCP_TOKEN="..."
export HF_TOKEN="..."
export CONTEXT7_API_KEY="..."   # 可选
paper-repro mcp enable github-readonly
paper-repro mcp enable huggingface

# 4. 完全重启
cd /path/to/project
paper-opencode --auto -m <provider>/<model>
```

升级不会删除项目 `.paper-repro/`、历史运行、项目 Conda、底座 API 或视觉路由。`paper-opencode` 会自动加载 `~/.config/paper-repro/opencode.mcp.runtime.json`。若你已经手工设置 `OPENCODE_CONFIG`，启动器会尊重该变量，此时需自行把运行配置合并进去或取消该变量。
