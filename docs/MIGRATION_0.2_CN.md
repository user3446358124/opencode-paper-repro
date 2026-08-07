# 从 0.1.x 迁移到 0.2.0

## 主要变化

| 0.1.x | 0.2.0 |
|---|---|
| 命令仅在 Starter `.opencode/` 中可用 | 命令安装到 OpenCode 全局配置 |
| `REPRO_ROOT` 通常等于当前目录 | 显式区分 workspace 与 install home |
| 状态位于 `.repro/` 和 `runs/` | 状态统一位于项目 `.paper-repro/` |
| 工具从 `context.worktree/scripts/reproctl.py` 调用 | 工具调用 Conda 中的 `paper-repro` |
| 失败只体现在退出码和日志 | 自动生成系统问题记录和反馈包 |

## 升级步骤

```bash
conda activate <原环境>
cd /path/to/new-starter
bash bootstrap.sh
```

完全退出并重新打开 OpenCode。

在目标项目中：

```bash
cd /path/to/project
paper-repro doctor
```

需要保留旧运行时：

```bash
paper-repro migrate-legacy
```

## 注意

- 不要继续从 Starter 目录启动论文项目复现。
- 新 run 默认不会读取旧 `.repro/current`。
- 旧数据不会被自动删除。
- OpenCode 已经运行时不会热加载新全局命令，必须重启。
