# 从 0.2.x 升级到 0.3.0

## 1. 在原控制环境更新

```bash
conda activate <原来安装 paper-repro 的控制环境>
cd /path/to/opencode-paper-repro-starter-v0.3.0
PAPER_REPRO_SKIP_DEPENDENCIES=1 bash bootstrap.sh
```

这会更新控制器、用户级 OpenCode 扩展和 `paper-opencode`/`paper-repro` 启动器，不重装主要依赖。

## 2. 重新加载 PATH

```bash
export PATH="$HOME/.local/bin:$PATH"
```

建议写入 `~/.bashrc`。

## 3. 为每个项目显式配置项目环境

0.2.x 默认把当前活动环境同时当控制环境和项目环境。0.3.0 推荐显式选择：

```bash
cd /path/to/project
paper-repro env use --name <已有项目环境>
```

或新建：

```bash
paper-repro env create --name <新环境名> --python 3.10
```

环境名不需要与项目文件夹同名。

## 4. 新启动方式

```bash
cd /path/to/project
paper-opencode --auto -m <provider>/<base-model>
```

完全退出升级前已运行的 OpenCode 进程，再启动。

## 5. 现有 run

原 `.paper-repro/runs/` 保留。读取旧 `state.json` 时，0.3.0 会为缺失的 pipeline/task 字段提供运行时默认值；新建 run 将完整写入双环境和 8 步状态。

## 6. 验证

```bash
paper-repro --version
paper-repro env show
paper-repro doctor
paper-repro status --watch
```
