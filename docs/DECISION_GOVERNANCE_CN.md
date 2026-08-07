# 自适应人工决策与自动化治理

适用版本：paper-repro **v0.8.0**

## 1. 为什么需要独立决策层

OpenCode 的 `--auto` 主要解决工具权限确认，例如是否允许执行 Bash、读取文件或写入允许目录。它不适合代替研究者做下面这些选择：

- 只复现主结果，还是同时运行消融与附录实验；
- 严格使用论文旧依赖，还是采用兼容的新版本；
- 遇到缺失实现时，是否修改算法语义来让代码跑通；
- 是否接受数据集许可、使用 gated 模型或产生付费 API/GPU 成本；
- 两种论文解释会导致不同结论时采用哪一种。

v0.8.0 将工具权限与研究决策分离：

```text
OpenCode 权限层
  └─ 这个工具能否执行？

paper-repro 决策层
  └─ 这个选择是否应该由用户决定？
```

因此即使使用：

```bash
paper-opencode --auto -m <provider>/<model>
```

高影响、不可逆、许可或外部副作用类决策仍会停在 paper-repro 检查点，不会因为 `--auto` 自动通过。

## 2. 默认模式

默认使用 `balanced`（平衡模式）。

| 模式 | 自动执行 | 通常询问 | 适用场景 |
|---|---|---|---|
| `autonomous` | L0–L2 中有安全默认项的选择 | L3 强制确认，以及没有安全默认项的选择 | 熟悉系统、希望少打断 |
| `balanced` | L0–L1 | L2–L3 | 默认推荐 |
| `collaborative` | L0 | L1–L3，但按预算和检查点合并 | 希望参与主要技术选择 |
| `strict` | 只有纯低风险记录项 | 所有实质影响选择 | 高价值或审计严格的复现 |

查看当前策略：

```bash
paper-repro decisions policy show
```

切换当前项目模式：

```bash
paper-repro decisions policy set \
  --scope workspace \
  --mode balanced
```

设置全局默认：

```bash
paper-repro decisions policy set \
  --scope global \
  --mode autonomous
```

OpenCode 中可以使用：

```text
/repro-decisions
/repro-decisions balanced
/repro-decisions pending
/repro-decisions checkpoint
```

## 3. 决策等级

### L0：自动执行并记录

典型特征：

- 低影响；
- 完全可逆；
- 有明显占优方案；
- 不改变论文结果或代码语义；
- 不产生明显成本或外部副作用。

例如：

- 在 `.paper-repro/cache/` 使用默认缓存目录；
- 运行只读静态检查；
- 为内部日志创建目录；
- 对已有文本层做第二次只读解析。

### L1：自动执行并通知

典型特征：

- 中低影响；
- 可回滚；
- 结果基本不受影响；
- 用户通常不需要逐项选择。

例如：

- 安装 README 明确指定的普通 Python 依赖；
- 对小规模公开资产进行可断点下载；
- 应用不改变数值语义的兼容性补丁；
- 选择唯一可行的官方入口。

### L2：用户确认，尽量合并询问

典型特征：

- 会影响复现覆盖范围、成本、时间或实现路径；
- 有两个以上合理选择；
- 选择不同会产生明显不同的结果或报告。

例如：

- 只复现主表，还是包含消融实验；
- 使用论文锁定环境，还是使用兼容的新环境；
- 下载 30 GB checkpoint，还是先运行无权重的轻量验证；
- 使用作者 release commit，还是仓库当前主分支；
- 运行 6 小时完整训练，还是先跑小规模评估。

### L3：强制人工确认

L3 不会被模式、偏好记忆或 `--auto` 绕过。

包括：

- 接受许可证、gated 数据或模型访问协议；
- 请求或扩大凭据权限；
- 删除、覆盖用户数据或不可逆操作；
- 系统级安装、驱动或内核修改；
- 向 GitHub、Hub 或其他外部系统写入、发布；
- 修改算法、loss、metric、数据划分等核心语义；
- 重大付费、外部副作用或关键证据高度不确定。

## 4. 决策评分依据

系统不会只看一个关键词，而是综合：

1. **影响范围**：low / medium / high / critical；
2. **可逆性**：reversible / partial / irreversible；
3. **模型置信度**；
4. **是否改变结果或实验语义**；
5. **是否产生外部副作用**；
6. **预计运行时间**；
7. **预计付费金额**；
8. **下载规模**；
9. **源代码修改范围**；
10. **类别是否属于永不自动执行的安全边界**。

默认阈值：

```json
{
  "large_download_gb": 20,
  "long_task_hours": 4,
  "paid_api_cny": 20,
  "source_patch_files": 5
}
```

这些阈值位于统一配置的 `decision_policy.thresholds`，可以按服务器和预算调整。

## 5. 控制用户负担

默认限制：

```json
{
  "max_interruptions_per_stage": 2,
  "max_interruptions_per_run": 8,
  "max_decisions_per_checkpoint": 3,
  "batch_related_decisions": true
}
```

含义：

- 单个阶段避免连续提出大量选择；
- 一次复现运行限制需要用户参与的决策数量；
- 每个检查点最多展示 3 个优先级最高的决策；
- 相关选择合并成一次询问，其余延后；
- 达到预算后，只有可逆、不改变结果且存在安全默认项的选择才能自动继续；
- 没有安全默认项或属于 L3 时仍然暂停。

调整示例：

```bash
paper-repro decisions policy set \
  --scope workspace \
  --max-interruptions-per-stage 1 \
  --max-interruptions-per-run 5 \
  --max-decisions-per-checkpoint 2
```

## 6. 决策检查点的展示格式

Agent 应一次性展示少量真正重要的选择：

```text
当前需要你确认 2 项决策：

1. 实验范围（推荐：只复现主表）
   A. 只复现主表：约 2 小时，覆盖核心结论，可稍后追加消融
   B. 主表 + 消融：约 9 小时，覆盖更完整

2. 环境路线（推荐：严格使用论文锁定版本）
   A. 锁定旧版本：复现一致性更高，编译风险较高
   B. 兼容新版本：安装更容易，可能出现数值差异
```

每项必须说明：

- 推荐选项；
- 时间与成本；
- 准确性或论文一致性；
- 是否可逆；
- 不选择时的后果。

不应询问抽象问题，例如“你想怎么做？”或“是否继续？”，而应给出可以直接执行的具体选项。

## 7. 查看与处理待决策项

查看：

```bash
paper-repro decisions list --pending
```

生成当前检查点：

```bash
paper-repro decisions checkpoint
```

只查看某阶段：

```bash
paper-repro decisions checkpoint --stage execution
```

手工确认：

```bash
paper-repro decisions resolve dec-xxxxxxxxxx \
  --option main \
  --note "优先复现论文核心表格"
```

待确认决策存在时，`repro_exec` 会返回退出码 `3`。全局 OpenCode 审计插件也会阻止非只读 Bash 命令和项目文件编辑，避免 Agent 绕过控制器：

```text
WAITING_FOR_DECISION: 当前有待确认决策，已阻止执行项目命令
```

这属于正常暂停，不会被写成 `SYSTEM_ISSUES.md` 中的系统故障。

## 8. 记住个性化偏好

某些重复决策可以保存偏好：

```bash
paper-repro decisions resolve dec-xxxxxxxxxx \
  --option main \
  --remember workspace
```

作用域：

- `none`：只对本次决策生效；
- `workspace`：仅当前项目；
- `global`：所有项目默认采用。

适合记住：

- 默认只复现主表；
- 优先使用官方 release；
- 优先采用严格锁定环境；
- 默认先执行 smoke test，再决定完整运行。

不允许记住并自动跳过：

- 许可接受；
- 凭据权限；
- 删除或不可逆操作；
- 系统级修改；
- 外部写入与发布。

项目偏好保存在：

```text
<workspace>/.paper-repro/config.json
```

全局偏好保存在：

```text
~/.config/paper-repro/config.json
```

## 9. 决策审计产物

每次运行保存：

```text
.paper-repro/current/meta/decisions.jsonl
.paper-repro/current/meta/decision-checkpoint.json
.paper-repro/current/report/DECISIONS.md
```

记录内容包括：

- 决策问题和候选选项；
- 风险等级与评分理由；
- 是自动执行还是用户确认；
- 推荐项、默认项和最终选择；
- 是否使用了历史偏好；
- 决策阶段、时间和用户备注。

最终报告可据此说明哪些结果来自用户选择，哪些是系统自动完成。

## 10. 推荐配置

### 日常论文复现

```bash
paper-repro decisions policy set --scope workspace --mode balanced
```

### 服务器租用时间有限，希望少打断

```bash
paper-repro decisions policy set \
  --scope workspace \
  --mode autonomous \
  --max-interruptions-per-run 4
```

### 需要教学或逐步参与

```bash
paper-repro decisions policy set \
  --scope workspace \
  --mode collaborative \
  --max-decisions-per-checkpoint 2
```

### 高价值结果或准备正式发布

```bash
paper-repro decisions policy set --scope workspace --mode strict
```

## 11. 能力边界

该机制能够强制阻止已经登记为待确认的决策，并对常见风险进行结构化分类；但“某个选择是否构成实质研究决策”仍需要 Agent 识别。纯文本底座可能漏掉隐含决策，因此系统还通过以下方式降低风险：

- 在总编排器和关键子代理中明确列出必须评估的场景；
- 将自动决策全部写入 `DECISIONS.md`；
- 对核心语义修改设为 L3；
- 在有待决策项时从控制器层阻止项目命令；
- 保留用户切换 `strict` 模式的能力。

对于正式发表、昂贵训练或受限数据，建议使用 `strict` 或 `collaborative`，并在运行结束后审阅 `DECISIONS.md`。
