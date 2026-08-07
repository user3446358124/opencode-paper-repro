#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${CONDA_PREFIX:-}" ]]; then
  echo "ERROR: 请先激活安装本系统的 Conda 环境。" >&2
  exit 2
fi

OPENCODE_CONFIG_HOME="${OPENCODE_CONFIG_HOME:-${XDG_CONFIG_HOME:-$HOME/.config}/opencode}"
INSTALL_HOME="${PAPER_REPRO_INSTALL_HOME:-$CONDA_PREFIX/share/opencode-paper-repro}"
USER_BIN="${PAPER_REPRO_USER_BIN:-$HOME/.local/bin}"

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
