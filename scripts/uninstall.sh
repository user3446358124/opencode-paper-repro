#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${CONDA_PREFIX:-}" ]]; then
  echo "ERROR: 请先激活安装本系统的 Conda 环境。" >&2
  exit 2
fi

OPENCODE_CONFIG_HOME="${OPENCODE_CONFIG_HOME:-${XDG_CONFIG_HOME:-$HOME/.config}/opencode}"
INSTALL_HOME="${PAPER_REPRO_INSTALL_HOME:-$CONDA_PREFIX/share/opencode-paper-repro}"
USER_BIN="${PAPER_REPRO_USER_BIN:-$HOME/.local/bin}"

canonical_path() {
  python - "$1" <<'PY_CANON'
import os, sys
print(os.path.realpath(os.path.expanduser(sys.argv[1])))
PY_CANON
}
INSTALL_HOME="$(canonical_path "$INSTALL_HOME")"
CONDA_PREFIX_REAL="$(canonical_path "$CONDA_PREFIX")"
HOME_REAL="$(canonical_path "$HOME")"
case "$INSTALL_HOME" in
  /|"$HOME_REAL"|"$CONDA_PREFIX_REAL")
    echo "ERROR: 拒绝危险卸载路径：$INSTALL_HOME" >&2
    exit 2
    ;;
esac
if [[ ! -f "$INSTALL_HOME/install.json" ]]; then
  echo "ERROR: $INSTALL_HOME 缺少 paper-repro install.json 标记，拒绝 rm -rf。" >&2
  exit 2
fi
MARKED_HOME="$(python - "$INSTALL_HOME/install.json" <<'PY_MARKER'
import json, os, sys
try:
    data=json.load(open(sys.argv[1], encoding='utf-8'))
    print(os.path.realpath(data.get('install_home','')))
except Exception:
    print('')
PY_MARKER
)"
if [[ "$MARKED_HOME" != "$INSTALL_HOME" ]]; then
  echo "ERROR: install.json 中的 install_home 与当前路径不一致，拒绝卸载。" >&2
  exit 2
fi

rm -f "$CONDA_PREFIX/bin/paper-repro"
rm -f "$USER_BIN/paper-repro" "$USER_BIN/paper-opencode"
rm -rf "$INSTALL_HOME"
rm -f "$CONDA_PREFIX/etc/conda/activate.d/paper-repro.sh" "$CONDA_PREFIX/etc/conda/deactivate.d/paper-repro.sh"

for file in \
  "$OPENCODE_CONFIG_HOME/commands/reproduce.md" \
  "$OPENCODE_CONFIG_HOME/commands/repro-status.md" \
  "$OPENCODE_CONFIG_HOME/commands/repro-resume.md" \
  "$OPENCODE_CONFIG_HOME/commands/repro-doctor.md" \
  "$OPENCODE_CONFIG_HOME/commands/repro-issues.md" \
  "$OPENCODE_CONFIG_HOME/commands/repro-feedback.md" \
  "$OPENCODE_CONFIG_HOME/commands/repro-env.md" \
  "$OPENCODE_CONFIG_HOME/commands/repro-decisions.md" \
  "$OPENCODE_CONFIG_HOME/commands/repro-explain.md" \
  "$OPENCODE_CONFIG_HOME/commands/repro-mcp.md" \
  "$OPENCODE_CONFIG_HOME/commands/repro-models.md" \
  "$OPENCODE_CONFIG_HOME/commands/repro-paper.md" \
  "$OPENCODE_CONFIG_HOME/commands/repro-improve.md" \
  "$OPENCODE_CONFIG_HOME/commands/repro-improvements.md" \
  "$OPENCODE_CONFIG_HOME/commands/repro-publish.md" \
  "$OPENCODE_CONFIG_HOME/commands/repro-publications.md" \
  "$OPENCODE_CONFIG_HOME/commands/repro-security.md" \
  "$OPENCODE_CONFIG_HOME/agents/repro-orchestrator.md" \
  "$OPENCODE_CONFIG_HOME/agents/paper-auditor.md" \
  "$OPENCODE_CONFIG_HOME/agents/repo-mapper.md" \
  "$OPENCODE_CONFIG_HOME/agents/coverage-judge.md" \
  "$OPENCODE_CONFIG_HOME/agents/asset-resolver.md" \
  "$OPENCODE_CONFIG_HOME/agents/environment-builder.md" \
  "$OPENCODE_CONFIG_HOME/agents/experiment-runner.md" \
  "$OPENCODE_CONFIG_HOME/agents/result-verifier.md" \
  "$OPENCODE_CONFIG_HOME/agents/report-writer.md" \
  "$OPENCODE_CONFIG_HOME/agents/code-explainer.md" \
  "$OPENCODE_CONFIG_HOME/agents/vision-auditor.md" \
  "$OPENCODE_CONFIG_HOME/agents/system-maintainer.md" \
  "$OPENCODE_CONFIG_HOME/agents/open-source-publisher.md" \
  "$OPENCODE_CONFIG_HOME/tools/repro.ts" \
  "$OPENCODE_CONFIG_HOME/plugins/repro-audit.ts"; do
  rm -f "$file"
done

echo "已卸载 OpenCode Paper Reproduction 控制层。项目中的 .paper-repro 数据与用户级 self-improve/publish 历史未删除。可分别执行 rm -rf ~/.local/state/opencode-paper-repro/self-improve 和 ~/.local/state/opencode-paper-repro/publish。"
