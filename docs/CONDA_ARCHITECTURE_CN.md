# Conda 双环境架构

## 1. 为什么分离

论文仓库常要求不同 Python、PyTorch、CUDA 用户态库和旧依赖。若 OpenCode 控制工具与项目依赖混装，一个项目的降级或冲突可能破坏整个自动化系统。

因此系统使用：

```text
固定控制环境
├── opencode
├── node
├── paper-repro
├── PDF/日志/下载工具
└── 底座模型接入

项目执行环境 A
├── 项目 A 的 Python/PyTorch/依赖
└── 训练与评测

项目执行环境 B
├── 项目 B 的 Python/PyTorch/依赖
└── 训练与评测
```

## 2. 用户级与系统级的含义

`~/.config/opencode/` 和 `~/.local/bin/` 是**当前 Linux 用户级**，不是整台服务器所有用户共享。

以 root 安装时，路径是：

```text
$HOME/.config/opencode/
$HOME/.local/bin/
```

其他 Linux 用户需要各自安装，或者由管理员建设共享方案。

## 3. 推荐命令

```bash
# 仅一次
conda create -n paper-repro-control python=3.11 -y
conda activate paper-repro-control
bash bootstrap.sh

# 每个项目
cd /path/to/project
paper-repro env create --name project-a-py310 --python 3.10
paper-opencode --auto -m <provider>/<base-model>
```

`paper-opencode` 会固定使用安装时的控制环境，即使当前 shell 先前激活了别的 Conda。

## 4. 执行环境检查

```bash
paper-repro env show
paper-repro doctor
paper-repro status --watch
```

输出同时展示：

- `CONTROL CONDA`：控制器所在环境；
- `PROJECT CONDA`：项目代码所在环境；
- 两者的绝对 prefix。

## 5. 环境配置文件

项目环境保存到：

```text
<workspace>/.paper-repro/config.json
```

示例：

```json
{
  "schema_version": 1,
  "execution_env": {
    "type": "conda",
    "name": "lead-repro-py310",
    "prefix": "$HOME/miniconda3/envs/example-repro-py310",
    "python": "$HOME/miniconda3/envs/example-repro-py310/bin/python"
  },
  "enforce_execution_env": true
}
```

工作区 `/srv/projects/example-paper` 与环境 `lead-repro-py310` 相互独立。
