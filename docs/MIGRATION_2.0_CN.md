# v1.0.0 → v2.0.0 覆盖升级说明

## 重要变化

v2.0.0 更换了 execution 生命周期：长任务不再由 OpenCode 工具调用同步持有，而进入独立 Task Registry/Scheduler。

已有 `.paper-repro/` 历史 run 不删除，但新 Runtime Contract 只对升级后新建的 run 完整生效。建议当前正在运行的 v1.x 长任务完成后再升级，不要在任务运行中替换执行器。

## 升级

```bash
# 1. 完全退出 OpenCode；当前 v1.x 长任务最好先结束
conda activate <paper-repro-control>

# 2. 解压 v2.0.0
cd /path/to/opencode-paper-repro-starter-v2.0.0

# 3. 覆盖系统代码；保留现有依赖
PAPER_REPRO_SKIP_DEPENDENCIES=1 bash bootstrap.sh
hash -r

# 4. 检查
paper-repro --version
paper-repro doctor
paper-repro gpu --help
paper-repro runtime --help
paper-repro remote --help
```

版本应为 `2.0.0`。

## 新 run 的 execution 使用方式

```bash
cd /path/to/project
paper-opencode --auto -m <provider>/<model>
```

执行 `/reproduce` 后，在进入 execution 时 OpenCode 会先列出 GPU 并询问本次允许使用的 GPU。

手工配置也可以：

```bash
paper-repro gpu prepare --json
paper-repro gpu configure --ids 0,1 --max-parallel 2
```

监控：

```bash
paper-repro status --watch
```

远程：

```bash
paper-repro remote discover --active --json
paper-repro --latest remote snapshot --json
```

## OpenCode 配置变化

v2.0 默认阻止 OpenCode bash 直接启动：

```text
python / python3 / pip / pip3
setsid / nohup
torchrun / accelerate / deepspeed
```

长任务应走 `repro_exec`/`repro_runtime`。这是为了避免 Agent 会话被几个小时的命令占住。
