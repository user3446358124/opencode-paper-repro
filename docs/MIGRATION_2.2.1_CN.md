# v2.2.0 → v2.2.1 安全加固升级说明

v2.2.1 不改变 Remote Contract v1 和 GPU Scheduler 的主要业务语义，但**项目执行安全默认值发生了重要变化**。

## 覆盖升级

完全退出 OpenCode，确保当前没有需要继续运行的旧 Scheduler 任务，然后：

```bash
conda activate <paper-repro-control>
unzip opencode-paper-repro-starter-v2.2.1.zip
cd opencode-paper-repro-starter
PAPER_REPRO_SKIP_DEPENDENCIES=1 bash bootstrap.sh
hash -r
```

希望同时应用固定控制层依赖（包括 control Conda 内的 `bubblewrap=0.11.2`）时，不使用 `PAPER_REPRO_SKIP_DEPENDENCIES=1`。只做快速覆盖升级会保留现有依赖；若此前没有 bwrap，项目执行会继续 fail-closed。

检查：

```bash
paper-repro --version
paper-repro doctor
paper-repro security show
paper-repro remote capabilities --json
```

## 重要行为变化

1. 新项目任务默认需要 `bwrap`。没有 `bwrap` 时不再静默以同 Linux 用户权限运行第三方代码。
2. 旧 v2.2.0 中已排队但尚未运行的 task，在 v2.2.1 恢复时也会采用新的 fail-closed 默认；如果服务器没有 `bwrap`，任务会被阻止。
3. 项目任务默认不会继承任何持久化 Token/API Key。
4. 需要模型/数据 Token 的任务必须先在 workspace 显式授权变量名，再在任务中声明。
5. 下载到 `/data`、`/mnt/...` 等 workspace 外目录，需要先加入 download-root 白名单。
6. 公开发布源码树中出现任何 symlink 都会阻断上传。
7. sandbox 不再暴露宿主整个根目录；真实 `.paper-repro` 控制状态会对项目进程隐藏，只保留 cache 与任务交换目录。
8. 项目 Conda 必须与控制 Conda 分离；安全模式下相同前缀会被拒绝。
9. 旧项目建议执行 `paper-repro security permissions repair --scope workspace --yes` 修复历史 644/755 状态文件。

## 可信仓库兼容模式

服务器暂时无法提供 `bwrap`，且仓库已经人工审核时：

```bash
paper-repro security sandbox set --mode trusted-off --yes
```

这不是等价安全模式。它只保留 Conda 隔离与密钥环境变量清洗，不能隔离同一用户的文件系统。
