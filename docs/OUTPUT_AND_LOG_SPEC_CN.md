# 输出与日志规范

## 1. 工作区级配置

```text
.paper-repro/config.json
```

记录项目执行 Conda，不依赖工作区文件夹名。

## 2. 状态模型

`meta/state.json` 同时记录：

- `control_env`：OpenCode/控制器环境；
- `execution_env`：项目执行环境；
- `pipeline`：总步骤、当前步骤、完成步骤和剩余步骤；
- `task`：当前任务的百分比、完成量、总量、单位、速度、ETA；
- `last_gpu`：最近 GPU 快照；
- `progress`：基于已完成步骤和当前任务计算的总体进度。

## 3. 命令日志

每个命令的日志头必须包含：

```text
run_id
stage
cwd
control_conda
project_conda
started_at
command（脱敏）
```

`commands.jsonl` 使用 start/finish 两条记录，保存退出码、耗时和日志路径。

## 4. 下载日志

`paper-repro download` 记录：

```text
URL（脱敏）
目标路径
续传起点
已完成字节
总字节
速度
ETA
SHA256
```

## 5. 步骤状态

标准步骤数为 8。代理调用 `repro_stage` 时应写入：

```text
step
step_total
step_name
step_status
```

## 6. 任务进度协议

```text
REPRO_PROGRESS current/total message
```

控制器将其写入 `task`，并计算任务 ETA 与总体进度。总数未知时不得伪造百分比。

## 7. 问题记录

系统级与 run 级问题都使用 JSONL 作为事实源，并渲染为 Markdown。反馈包默认脱敏，不包含完整密钥或 `.env`。


## 决策记录

```text
meta/decisions.jsonl
meta/decision-checkpoint.json
report/DECISIONS.md
```

记录自动决策、待确认选项、评分理由、最终选择和偏好作用域。
