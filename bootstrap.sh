#!/usr/bin/env bash
set -euo pipefail

SYSTEM_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "${CONDA_PREFIX:-}" ]]; then
  echo "ERROR: 请先激活 Conda 环境。" >&2
  exit 2
fi
if [[ "${CONDA_DEFAULT_ENV:-}" == "base" ]]; then
  echo "ERROR: 不允许在 base 环境中安装。请创建专用 Conda 环境。" >&2
  exit 2
fi

OPENCODE_VERSION="${OPENCODE_VERSION:-latest}"
PYTHON="${PYTHON:-python}"
INSTALL_HOME="${PAPER_REPRO_INSTALL_HOME:-$CONDA_PREFIX/share/opencode-paper-repro}"
OPENCODE_CONFIG_HOME="${OPENCODE_CONFIG_HOME:-${XDG_CONFIG_HOME:-$HOME/.config}/opencode}"
GLOBAL_INSTALL="${PAPER_REPRO_GLOBAL_INSTALL:-1}"
SKIP_DEPENDENCIES="${PAPER_REPRO_SKIP_DEPENDENCIES:-0}"
USER_BIN="${PAPER_REPRO_USER_BIN:-$HOME/.local/bin}"
CONDA_EXE_PATH="${CONDA_EXE:-$(type -P conda 2>/dev/null || true)}"
PAPER_REPRO_CONFIG_HOME="${PAPER_REPRO_CONFIG_HOME:-${XDG_CONFIG_HOME:-$HOME/.config}/paper-repro}"
MCP_RUNTIME_CONFIG="$PAPER_REPRO_CONFIG_HOME/opencode.mcp.runtime.json"
CONFIG_FILE="${PAPER_REPRO_CONFIG_FILE:-$PAPER_REPRO_CONFIG_HOME/config.json}"
SECRETS_FILE="$CONFIG_FILE"

mkdir -p "$INSTALL_HOME" "$CONDA_PREFIX/bin"

if [[ "$SKIP_DEPENDENCIES" != "1" ]]; then
  # 强制 Node.js 来自当前 Conda 环境，避免复现控制层依赖宿主机 Node。
  NODE_PATH="$(command -v node 2>/dev/null || true)"
  if [[ -z "$NODE_PATH" || "$(readlink -f "$NODE_PATH")" != "$CONDA_PREFIX/bin/node" ]]; then
    conda install -y -c conda-forge nodejs
    hash -r
  fi

  npm install -g --prefix "$CONDA_PREFIX" "opencode-ai@${OPENCODE_VERSION}"

  # GitHub CLI is installed in the control Conda for privacy-gated publication.
  GH_PATH="$(command -v gh 2>/dev/null || true)"
  if [[ -z "$GH_PATH" || "$(readlink -f "$GH_PATH")" != "$CONDA_PREFIX/bin/gh" ]]; then
    conda install -y -c conda-forge gh
    hash -r
  fi

  "$PYTHON" -m pip install --upgrade pip
  "$PYTHON" -m pip install \
    pymupdf pypdf huggingface_hub rich psutil pyyaml requests tqdm pandas packaging
else
  echo "跳过 Node.js、OpenCode 和 Python 依赖安装，仅更新控制器与全局扩展。"
fi

# 将控制器安装到 Conda 环境。项目目录移动后，paper-repro 命令仍然有效。
rm -rf "$INSTALL_HOME/scripts" "$INSTALL_HOME/schemas" "$INSTALL_HOME/docs" "$INSTALL_HOME/configs" "$INSTALL_HOME/opencode-profile" "$INSTALL_HOME/source"
mkdir -p "$INSTALL_HOME/scripts" "$INSTALL_HOME/schemas" "$INSTALL_HOME/docs" "$INSTALL_HOME/configs" "$INSTALL_HOME/opencode-profile" "$INSTALL_HOME/source"
# Install the whole scripts/ directory: helper modules imported by
# reproctl.py (e.g. gpu_policy.py) must be installed as well.
# The CLI entry runs via python, so no executable bit is required.
cp -a "$SYSTEM_HOME/scripts/." "$INSTALL_HOME/scripts/"
install -m 644 "$SYSTEM_HOME/VERSION" "$INSTALL_HOME/VERSION"
cp -a "$SYSTEM_HOME/schemas/." "$INSTALL_HOME/schemas/"
cp -a "$SYSTEM_HOME/docs/." "$INSTALL_HOME/docs/"
cp -a "$SYSTEM_HOME/configs/." "$INSTALL_HOME/configs/"
cp -a "$SYSTEM_HOME/.opencode/." "$INSTALL_HOME/opencode-profile/"

# 保留一个不含用户密钥/运行状态的完整源码快照，供受控自我迭代在隔离副本中修改和回归测试。
for item in scripts schemas docs configs .opencode .github tests bootstrap.sh README.md CONTRIBUTING.md AGENTS.md CHANGELOG_CN.md USAGE_CN.md VERSION opencode.jsonc .gitignore; do
  if [[ -e "$SYSTEM_HOME/$item" ]]; then
    if [[ -d "$SYSTEM_HOME/$item" ]]; then
      mkdir -p "$INSTALL_HOME/source/$item"
      cp -a "$SYSTEM_HOME/$item/." "$INSTALL_HOME/source/$item/"
    else
      cp -a "$SYSTEM_HOME/$item" "$INSTALL_HOME/source/$item"
    fi
  fi
done

cat > "$CONDA_PREFIX/bin/paper-repro" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec "$CONDA_PREFIX/bin/python" "$INSTALL_HOME/scripts/reproctl.py" "\$@"
EOF
chmod +x "$CONDA_PREFIX/bin/paper-repro"

# 激活环境时公开安装位置，便于诊断与升级。
mkdir -p "$CONDA_PREFIX/etc/conda/activate.d" "$CONDA_PREFIX/etc/conda/deactivate.d"
cat > "$CONDA_PREFIX/etc/conda/activate.d/paper-repro.sh" <<EOF
export PAPER_REPRO_INSTALL_HOME="$INSTALL_HOME"
export PAPER_REPRO_SOURCE_HOME="$INSTALL_HOME/source"
export PAPER_REPRO_CONDA_EXE="$CONDA_EXE_PATH"
export PAPER_REPRO_CONFIG_HOME="$PAPER_REPRO_CONFIG_HOME"
export PAPER_REPRO_MCP_CONFIG="$MCP_RUNTIME_CONFIG"
export PAPER_REPRO_CONFIG_FILE="$CONFIG_FILE"
export PAPER_REPRO_SECRETS_FILE="$CONFIG_FILE"
EOF
cat > "$CONDA_PREFIX/etc/conda/deactivate.d/paper-repro.sh" <<'EOF'
unset PAPER_REPRO_INSTALL_HOME
unset PAPER_REPRO_SOURCE_HOME
unset PAPER_REPRO_CONDA_EXE
unset PAPER_REPRO_CONFIG_HOME
unset PAPER_REPRO_MCP_CONFIG
unset PAPER_REPRO_CONFIG_FILE
unset PAPER_REPRO_SECRETS_FILE
EOF
export PAPER_REPRO_INSTALL_HOME="$INSTALL_HOME"
export PAPER_REPRO_SOURCE_HOME="$INSTALL_HOME/source"

# OpenCode 官方支持全局 commands/agents/tools/plugins 目录。安装后可在任意项目启动 opencode。
if [[ "$GLOBAL_INSTALL" == "1" ]]; then
  BACKUP_HOME="$OPENCODE_CONFIG_HOME/paper-repro-backup/$(date +%Y%m%d-%H%M%S)"
  BACKED_UP=0
  for directory in commands agents tools plugins; do
    mkdir -p "$OPENCODE_CONFIG_HOME/$directory"
    while IFS= read -r -d '' source_file; do
      relative="${source_file#"$SYSTEM_HOME/.opencode/"}"
      destination="$OPENCODE_CONFIG_HOME/$relative"
      if [[ -f "$destination" ]] && ! cmp -s "$source_file" "$destination"; then
        mkdir -p "$BACKUP_HOME/$(dirname "$relative")"
        cp -a "$destination" "$BACKUP_HOME/$relative"
        BACKED_UP=1
      fi
      install -m 644 "$source_file" "$destination"
    done < <(find "$SYSTEM_HOME/.opencode/$directory" -maxdepth 1 -type f -print0)
  done

  for launcher in paper-repro paper-opencode; do
    if [[ -f "$USER_BIN/$launcher" ]]; then
      mkdir -p "$BACKUP_HOME/user-bin"
      cp -a "$USER_BIN/$launcher" "$BACKUP_HOME/user-bin/$launcher"
      BACKED_UP=1
    fi
  done
  if [[ "$BACKED_UP" == "1" ]]; then
    echo "已有 OpenCode 扩展或启动器已备份到：$BACKUP_HOME"
  else
    rmdir "$BACKUP_HOME" 2>/dev/null || true
    rmdir "$(dirname "$BACKUP_HOME")" 2>/dev/null || true
  fi

  # User-global launchers keep the control Conda environment separate from each project's Conda environment.
  mkdir -p "$USER_BIN"
  cat > "$USER_BIN/paper-repro" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export PATH="$CONDA_PREFIX/bin:\$PATH"
export CONDA_PREFIX="$CONDA_PREFIX"
export CONDA_DEFAULT_ENV="${CONDA_DEFAULT_ENV:-paper-repro-control}"
export PAPER_REPRO_INSTALL_HOME="$INSTALL_HOME"
export PAPER_REPRO_SOURCE_HOME="$INSTALL_HOME/source"
export PAPER_REPRO_CONDA_EXE="$CONDA_EXE_PATH"
export PAPER_REPRO_CONFIG_HOME="$PAPER_REPRO_CONFIG_HOME"
export PAPER_REPRO_MCP_CONFIG="$MCP_RUNTIME_CONFIG"
export PAPER_REPRO_CONFIG_FILE="$CONFIG_FILE"
export PAPER_REPRO_SECRETS_FILE="$CONFIG_FILE"
exec "$CONDA_PREFIX/bin/python" "$INSTALL_HOME/scripts/reproctl.py" "\$@"
EOF
  chmod +x "$USER_BIN/paper-repro"

  cat > "$USER_BIN/paper-opencode" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export PATH="$CONDA_PREFIX/bin:\$PATH"
export CONDA_PREFIX="$CONDA_PREFIX"
export CONDA_DEFAULT_ENV="${CONDA_DEFAULT_ENV:-paper-repro-control}"
export PAPER_REPRO_INSTALL_HOME="$INSTALL_HOME"
export PAPER_REPRO_SOURCE_HOME="$INSTALL_HOME/source"
export PAPER_REPRO_CONDA_EXE="$CONDA_EXE_PATH"
export PAPER_REPRO_CONFIG_HOME="$PAPER_REPRO_CONFIG_HOME"
export PAPER_REPRO_MCP_CONFIG="$MCP_RUNTIME_CONFIG"
export PAPER_REPRO_CONFIG_FILE="$CONFIG_FILE"
export PAPER_REPRO_SECRETS_FILE="$CONFIG_FILE"
export OPENCODE_ENABLE_EXA="\${OPENCODE_ENABLE_EXA:-1}"
"$CONDA_PREFIX/bin/python" "$INSTALL_HOME/scripts/reproctl.py" mcp sync --quiet >/dev/null 2>&1 || true
if [[ -z "\${OPENCODE_CONFIG:-}" ]]; then
  export OPENCODE_CONFIG="$MCP_RUNTIME_CONFIG"
fi
exec "$CONDA_PREFIX/bin/python" "$INSTALL_HOME/scripts/reproctl.py" secrets exec -- "$CONDA_PREFIX/bin/opencode" "\$@"
EOF
  chmod +x "$USER_BIN/paper-opencode"
fi


mkdir -p "$PAPER_REPRO_CONFIG_HOME"
chmod 700 "$PAPER_REPRO_CONFIG_HOME" 2>/dev/null || true
"$CONDA_PREFIX/bin/python" "$INSTALL_HOME/scripts/reproctl.py" secrets init --quiet
"$CONDA_PREFIX/bin/python" "$INSTALL_HOME/scripts/reproctl.py" mcp install-basic --quiet

cat > "$INSTALL_HOME/install.json" <<JSON
{
  "system_version": "$(cat "$SYSTEM_HOME/VERSION")",
  "installed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "source": "$SYSTEM_HOME",
  "install_home": "$INSTALL_HOME",
  "source_snapshot": "$INSTALL_HOME/source",
  "self_improvement_enabled": true,
  "github_publication_enabled": true,
  "conda_prefix": "$CONDA_PREFIX",
  "conda_env": "${CONDA_DEFAULT_ENV:-unknown}",
  "conda_executable": "$CONDA_EXE_PATH",
  "python": "$(command -v "$PYTHON")",
  "node": "$(command -v node)",
  "opencode": "$(command -v opencode)",
  "opencode_version": "$(opencode --version 2>/dev/null || true)",
  "github_cli": "$(command -v gh 2>/dev/null || true)",
  "github_cli_version": "$(gh --version 2>/dev/null | head -1 || true)",
  "global_opencode_config": "$OPENCODE_CONFIG_HOME",
  "user_bin": "$USER_BIN",
  "global_paper_repro_launcher": "$USER_BIN/paper-repro",
  "global_opencode_launcher": "$USER_BIN/paper-opencode",
  "mcp_runtime_config": "$MCP_RUNTIME_CONFIG",
  "unified_config_file": "$CONFIG_FILE",
  "native_websearch_enabled": true,
  "global_extensions_installed": $([[ "$GLOBAL_INSTALL" == "1" ]] && echo true || echo false)
}
JSON

chmod +x "$SYSTEM_HOME/scripts/reproctl.py"

echo "Bootstrap 完成：OpenCode Paper Reproduction $(cat "$SYSTEM_HOME/VERSION")"
echo "Conda 环境：${CONDA_DEFAULT_ENV}"
echo "控制命令：$(command -v paper-repro)"
if [[ "$GLOBAL_INSTALL" == "1" ]]; then
  echo "当前 Linux 用户的全局 OpenCode 扩展：$OPENCODE_CONFIG_HOME"
  echo "全局控制命令：$USER_BIN/paper-repro"
  echo "全局 OpenCode 启动器：$USER_BIN/paper-opencode"
  if [[ ":$PATH:" != *":$USER_BIN:"* ]]; then
    echo "WARNING: $USER_BIN 尚未出现在 PATH。请将以下内容加入 ~/.bashrc："
    echo "  export PATH=\"$USER_BIN:\$PATH\""
  fi
  echo "同一 Linux 用户下只需安装一次；每个项目仅需配置其项目 Conda 环境。"
  echo "建议从目标目录执行 paper-opencode，而不是在项目环境中重复安装 OpenCode。"
else
  echo "未安装全局扩展。请设置 OPENCODE_CONFIG_DIR=$INSTALL_HOME/opencode-profile 后启动 OpenCode。"
fi
echo "建议先运行：paper-repro doctor"
echo "模型路由：paper-repro models show（系统不预设或硬编码底座/视觉模型）"
echo "统一配置文件：$CONFIG_FILE（权限 600；包含 secrets/model_routing/mcp/decision_policy）"
echo "查看密钥状态：paper-repro secrets list"
echo "基础联网/MCP：paper-repro mcp status（内建 websearch 与 Context7 已启用）"
echo "自适应决策：paper-repro decisions policy show（默认 balanced）"
echo "受控自我迭代：paper-repro improve policy show（默认 guarded；仅系统 issue 或显式用户请求）"
echo "GitHub 开源发布：paper-repro publish policy show（只发布隔离系统源码快照；上传前强制隐私扫描与人工确认）"
