# 系统功能反馈与项目阻塞分离

## 1. 两类记录

### 系统功能问题

只回答 paper-repro / OpenCode 集成本身是否正常工作、是否安全、是否容易观察和是否有优化空间，例如：

- `/reproduce` 没有加载；
- 工作区识别错误；
- 控制 Conda 与项目 Conda 隔离失效；
- `status --watch` 信息错误或缺失；
- 下载进度、GPU、ETA 不更新；
- PDF 文本/视觉路由没有按策略执行；
- API 配置、模型路由或 MCP 模板存在系统缺陷；
- 日志脱敏、反馈包、升级或卸载异常；
- 可用性、性能、中文化和交互优化建议。

位置：

```text
.paper-repro/system/SYSTEM_ISSUES.md
.paper-repro/system/issues.jsonl
```

命令：

```bash
paper-repro issue add \
  --title "状态页未显示视觉调用次数" \
  --details "targeted 审计已完成，但状态页没有 provenance" \
  --category progress-ui \
  --expected "显示文本/视觉调用来源" \
  --optimization "增加视觉调用计数和页面列表"

paper-repro issue list --all
paper-repro issue resolve SYS-ID --resolution "修复说明"
```

### 项目复现阻塞项

只描述某一论文或仓库的具体问题，例如：

- checkpoint 或数据集未公开；
- 项目依赖冲突；
- 某训练命令报错；
- README 参数缺失；
- 论文实现不完整；
- GPU 显存不足。

位置：

```text
.paper-repro/current/report/RUN_BLOCKERS.md
.paper-repro/current/meta/blockers.jsonl
```

命令：

```bash
paper-repro blocker add --title "缺少 checkpoint" --details "README 链接已失效" --stage assets
paper-repro blocker list --all
paper-repro blocker resolve BLOCK-ID --resolution "已从作者 Release 获取"
```

项目阻塞默认不会进入系统反馈包。

## 2. 系统反馈包

```bash
paper-repro doctor
paper-repro feedback
```

默认仅包含：

- `feedback_manifest.json`；
- `SYSTEM_ISSUES.md`；
- 系统 issue 事件；
- doctor 诊断；
- OpenCode/paper-repro 系统事件（如存在）。

默认不包含：

- 项目源码；
- `RUN_BLOCKERS.md`；
- 项目命令记录；
- 数据集、模型和实验结果；
- 当前 run 的完整状态和日志。

显式增加最小元数据：

```bash
paper-repro feedback --include-workspace-metadata --include-run-metadata
```

只有排查系统工具执行异常时才加入截断日志：

```bash
paper-repro feedback --include-logs
```

## 3. 推荐反馈字段

系统问题应尽量包含：

1. 系统版本；
2. 组件和类别；
3. 触发操作；
4. 预期行为；
5. 实际行为；
6. 是否稳定复现；
7. 对复现流程的影响；
8. 可行的优化建议；
9. 必要的脱敏日志。

不要把某个项目的模型结构、私有路径、数据内容或训练结果当作系统问题主体。
