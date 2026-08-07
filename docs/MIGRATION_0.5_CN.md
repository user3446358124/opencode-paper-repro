# 升级到 v0.5.0

## 覆盖安装

完全退出 OpenCode，在原控制 Conda 中执行：

```bash
conda activate <paper-repro 控制环境>
cd /path/to/opencode-paper-repro-starter-v0.5.0
PAPER_REPRO_SKIP_DEPENDENCIES=1 bash bootstrap.sh
hash -r
```

然后从目标项目重启：

```bash
cd /path/to/project
paper-repro doctor
paper-opencode --auto -m <provider>/<model>
```

全局 Commands、Agents、Tools 和 Plugin 会覆盖为 v0.5.0；已有同名文件会先备份。项目 `.paper-repro/`、模型路由、项目 Conda 和历史 run 不删除。

## 旧问题文件

v0.4 及更早的 `RUN_ISSUES.md` 可能同时包含系统问题和项目问题。v0.5 不自动重分类旧内容，以免误判。

新 run 使用：

```text
SYSTEM_ISSUES.md      系统功能与优化问题
RUN_BLOCKERS.md       单个论文项目阻塞项
```

旧兼容链接 `RUN_ISSUES.md` 会指向新 run 的 `RUN_BLOCKERS.md`，但新文档和命令均使用新名称。

## PDF 策略

升级后每个项目默认获得：

```json
{
  "paper_audit": {
    "vision_policy": "targeted",
    "vision_verify_tables": true,
    "vision_verify_method_figures": true,
    "max_vision_pages": 24,
    "dpi": 200
  }
}
```

检查：

```bash
paper-repro paper policy show
paper-repro paper inspect --input /path/paper.pdf
```

## 新命令

```text
/repro-explain all
/repro-paper /path/paper.pdf
/repro-mcp
```

```bash
paper-repro code index
paper-repro code show
paper-repro paper policy show
paper-repro paper inspect --input paper.pdf
paper-repro blocker list
paper-repro mcp recommend
```
