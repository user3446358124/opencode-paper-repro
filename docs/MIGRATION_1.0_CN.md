# v1.0.0 覆盖升级说明

完全退出 OpenCode，然后在原控制 Conda 中执行：

```bash
conda activate <paper-repro-control>
unzip opencode-paper-repro-starter-v1.0.0.zip
cd opencode-paper-repro-starter
# 若控制环境还没有 gh，推荐直接完整安装
bash bootstrap.sh

# 已经自行安装 gh 时，也可只覆盖系统文件
# PAPER_REPRO_SKIP_DEPENDENCIES=1 bash bootstrap.sh
hash -r
```

检查：

```bash
paper-repro --version
paper-repro publish policy show
paper-repro publish auth status
paper-repro doctor
```

旧的统一密钥、视觉模型路由、MCP、决策策略、自我迭代队列、项目 Conda、历史 run 和日志都会保留。

v1.0.0 不会自动创建 GitHub 仓库，也不会自动推送。首次使用执行：

```bash
paper-repro publish configure --interactive
```

推荐先使用 `gh auth login`，不要在聊天中粘贴 Token。

## GitHub CLI 检查

```bash
which gh
gh --version
```

若使用跳过依赖模式且找不到 `gh`：

```bash
conda install -y -c conda-forge gh
```

## 首次发布建议

1. 先执行 `paper-repro publish configure --interactive`；
2. 首次选择 `private`；
3. 执行 `prepare`、`review`，在 GitHub 页面再检查一次；
4. 确认安全后再由你主动改为 `public`；
5. 公共仓库必须使用许可证，当前内置自动生成 MIT。
