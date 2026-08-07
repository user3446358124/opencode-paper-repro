# v0.8.0 覆盖升级说明

v0.8.0 新增自适应人工决策层，不删除已有项目、运行日志、模型路由、MCP 或密钥配置。

## 覆盖安装

完全退出 OpenCode，然后在原控制 Conda 中执行：

```bash
conda activate <paper-repro-control>
cd /path/to/opencode-paper-repro-starter-v0.8.0
PAPER_REPRO_SKIP_DEPENDENCIES=1 bash bootstrap.sh
hash -r
```

重新启动：

```bash
cd /path/to/project
paper-repro --version
paper-repro decisions policy show
paper-opencode --auto -m <provider>/<model>
```

版本应为 `0.8.0`，默认决策模式为 `balanced`。

## 新增命令

```bash
paper-repro decisions policy show
paper-repro decisions policy set --scope workspace --mode balanced
paper-repro decisions list --pending
paper-repro decisions checkpoint
paper-repro decisions resolve <ID> --option <OPTION>
```

OpenCode 新增：

```text
/repro-decisions
```

## 与 `--auto` 的关系

升级后仍可使用 `paper-opencode --auto`。它自动批准 OpenCode 工具权限，但不会自动通过 paper-repro 的 L2/L3 语义决策。待确认决策会阻止 `repro_exec`，直到用户选择。

## 兼容性

- 旧版 `.paper-repro/config.json` 会自动补充空的决策策略与偏好字段；
- 旧 run 不包含 `DECISIONS.md`，不影响查看和继续运行；
- 新 run 会创建 `meta/decisions.jsonl` 与 `report/DECISIONS.md`；
- 等待用户决策是正常状态，不会计入系统功能问题；
- 统一配置重置命令仍可删除决策策略和全局偏好。
