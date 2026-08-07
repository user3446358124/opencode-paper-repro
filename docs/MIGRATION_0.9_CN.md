# v0.9.0 覆盖升级说明

完全退出 OpenCode，在原控制 Conda 中执行：

```bash
conda activate <paper-repro控制环境>
unzip opencode-paper-repro-starter-v0.9.0.zip
cd opencode-paper-repro-starter
PAPER_REPRO_SKIP_DEPENDENCIES=1 bash bootstrap.sh
hash -r
```

检查：

```bash
paper-repro --version
paper-repro improve policy show
paper-repro improve list
paper-repro doctor
```

v0.9.0 会在控制环境安装目录新增不含用户密钥和运行状态的完整源码快照：

```text
$CONDA_PREFIX/share/opencode-paper-repro/source/
```

它是受控自我迭代的基线。已有统一配置、API Key、视觉路由、MCP、决策策略、项目 Conda、历史 run 和日志不会删除。

新 OpenCode 命令：

```text
/repro-improve <SYS-ID 或系统改进要求>
/repro-improvements
```

应用自我迭代补丁后，必须完全重启 OpenCode。
