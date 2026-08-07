#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
SERVER_PID=""
cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

CONTROL="$TMP/conda/control"
PROJECT_ENV="$TMP/conda/project-runtime"
FAKE_BIN="$TMP/bin"
mkdir -p "$CONTROL/bin" "$CONTROL/conda-meta" "$PROJECT_ENV/bin" "$PROJECT_ENV/conda-meta" "$FAKE_BIN"
ln -s "$(command -v python)" "$CONTROL/bin/python"
ln -s "$(command -v python)" "$PROJECT_ENV/bin/python"

cat > "$FAKE_BIN/conda" <<SCRIPT
#!/usr/bin/env bash
set -euo pipefail
if [[ "\${1:-} \${2:-} \${3:-}" == "env list --json" ]]; then
  printf '{"envs":["$CONTROL","$PROJECT_ENV"]}\n'
  exit 0
fi
if [[ "\${1:-}" == "run" ]]; then
  shift
  while [[ \$# -gt 0 ]]; do
    case "\$1" in
      --no-capture-output) shift ;;
      -p) export SMOKE_PROJECT_PREFIX="\$2"; shift 2 ;;
      *) break ;;
    esac
  done
  exec "\$@"
fi
echo "unsupported fake conda command" >&2
exit 2
SCRIPT
chmod +x "$FAKE_BIN/conda"

# Fake dual-GPU host: GPU 0 uses less memory than GPU 1, so auto-selection must pick GPU 0.
cat > "$FAKE_BIN/nvidia-smi" <<'SMIMOCK'
#!/usr/bin/env bash
if [[ "${1:-}" == "-q" ]]; then
  echo "fake nvidia-smi"
  exit 0
fi
cat <<'CSV'
0, NVIDIA A100-PCIE-40GB, GPU-00000000-0000-0000-0000-000000000000, 0, 1024, 40960, 28, 35
1, NVIDIA A100-PCIE-40GB, GPU-00000000-0000-0000-0000-000000000001, 0, 2048, 40960, 28, 36
CSV
SMIMOCK
chmod +x "$FAKE_BIN/nvidia-smi"

export PATH="$FAKE_BIN:$PATH"
export CONDA_PREFIX="$CONTROL"
export CONDA_DEFAULT_ENV="paper-repro-control-test"
export XDG_STATE_HOME="$TMP/global-state"
export TERM="${TERM:-xterm}"
# Isolate this test from any outer OpenCode workspace injection: repro_* tools set
# REPRO_WORKSPACE, which would otherwise redirect init/env/exec into the caller's
# real workspace and corrupt its config.json.
unset REPRO_WORKSPACE REPRO_STATE_HOME REPRO_RUN_DIR CONDA_EXE PAPER_REPRO_CONDA_EXE \
  PAPER_REPRO_MCP_CONFIG PAPER_REPRO_MODEL_ROUTING PAPER_REPRO_SECRETS_FILE \
  PAPER_REPRO_SOURCE_HOME PAPER_REPRO_INSTALL_HOME 2>/dev/null || true

PROJECT="$TMP/project"
mkdir -p "$PROJECT/subdir"
cd "$PROJECT"
git init -q
git config user.email smoke@example.com
git config user.name Smoke
printf 'smoke\n' > README.md
cat > main.py <<'PYCODE'
import argparse
from model import Model

def train(x):
    return Model().forward(x)

if __name__ == '__main__':
    argparse.ArgumentParser()
    train(1)
PYCODE
cat > model.py <<'PYCODE'
class Model:
    def forward(self, x):
        return x
PYCODE
git add README.md main.py model.py
git commit -qm smoke

python "$ROOT/scripts/reproctl.py" init --repository smoke --paper smoke.pdf >/dev/null
python "$ROOT/scripts/reproctl.py" env use --prefix "$PROJECT_ENV" >/dev/null
python "$ROOT/scripts/reproctl.py" stage --stage paper-audit --status running --step 1 --step-total 8 --step-status running >/dev/null

cd "$PROJECT/subdir"
python "$ROOT/scripts/reproctl.py" status --json | grep -q '"run_id"'
python "$ROOT/scripts/reproctl.py" exec --stage smoke --command \
  'python -c "import os; print(os.environ.get(\"SMOKE_PROJECT_PREFIX\")); print(\"CUDA_VISIBLE_DEVICES=\" + str(os.environ.get(\"CUDA_VISIBLE_DEVICES\"))); print(\"REPRO_PROGRESS 1/1 done\")"' \
  --timeout 30 > "$TMP/exec.out"
grep -q "$PROJECT_ENV" "$TMP/exec.out"
grep -q 'CUDA_VISIBLE_DEVICES=0' "$TMP/exec.out"

# Explicit GPU selection: --gpus 1 must pin CUDA_VISIBLE_DEVICES=1 on the second card.
python "$ROOT/scripts/reproctl.py" exec --stage smoke-gpus-1 --command \
  'python -c "import os; print(\"CUDA_VISIBLE_DEVICES=\" + str(os.environ.get(\"CUDA_VISIBLE_DEVICES\")))"' \
  --gpus 1 --timeout 30 > "$TMP/exec-gpus1.out"
grep -q 'CUDA_VISIBLE_DEVICES=1' "$TMP/exec-gpus1.out"

# --gpus none must leave CUDA_VISIBLE_DEVICES unset.
python "$ROOT/scripts/reproctl.py" exec --stage smoke-gpus-none --command \
  'python -c "import os; print(\"CUDA_VISIBLE_DEVICES=\" + str(os.environ.get(\"CUDA_VISIBLE_DEVICES\")))"' \
  --gpus none --timeout 30 > "$TMP/exec-gpus-none.out"
grep -q 'CUDA_VISIBLE_DEVICES=None' "$TMP/exec-gpus-none.out"

# A command that sets CUDA_VISIBLE_DEVICES itself must not be overridden.
python "$ROOT/scripts/reproctl.py" exec --stage smoke-gpus-explicit --command \
  'CUDA_VISIBLE_DEVICES=1 python -c "import os; print(\"CUDA_VISIBLE_DEVICES=\" + str(os.environ.get(\"CUDA_VISIBLE_DEVICES\")))"' \
  --timeout 30 > "$TMP/exec-gpus-explicit.out"
grep -q 'CUDA_VISIBLE_DEVICES=1' "$TMP/exec-gpus-explicit.out"

python "$ROOT/scripts/reproctl.py" stage --stage paper-audit --status completed --step 1 --step-total 8 --step-status completed >/dev/null
python "$ROOT/scripts/reproctl.py" status --json > "$TMP/status.json"
python - "$TMP/status.json" <<'PY'
import json, sys
state = json.load(open(sys.argv[1], encoding="utf-8"))
assert state["pipeline"]["completed_steps"] == 1
assert state["pipeline"]["remaining_steps"] == 7
assert state["execution_env"]["configured"] is True
assert state["task"]["status"] == "idle"
PY

# Adaptive decision governance: low-risk choices auto-log, material choices pause once,
# execution is blocked without creating a system issue, and workspace preferences persist.
python "$ROOT/scripts/reproctl.py" decisions policy set --mode balanced --scope workspace >/dev/null
python "$ROOT/scripts/reproctl.py" decisions assess \
  --title '选择临时索引目录' --question '是否使用默认缓存目录？' \
  --category routine --stage repo-audit --impact low --reversibility reversible --confidence 0.99 \
  --options-json '[{"id":"default","label":"使用默认目录","recommended":true},{"id":"custom","label":"使用自定义目录"}]' \
  --default-option default --recommended-option default >/dev/null
python "$ROOT/scripts/reproctl.py" decisions assess \
  --title '选择实验覆盖范围' --question '只复现主表还是包含消融？' \
  --category experiment-scope --stage execution --impact high --reversibility reversible --confidence 0.9 --changes-results \
  --options-json '[{"id":"main","label":"只复现主表","consequence":"较快","recommended":true},{"id":"all","label":"主表与消融","consequence":"更完整但更慢"}]' \
  --default-option main --recommended-option main --preference-key experiment.scope > "$TMP/decision.json"
DECISION_ID="$(python - "$TMP/decision.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding='utf-8'))['decision_id'])
PY
)"
set +e
python "$ROOT/scripts/reproctl.py" exec --stage blocked-by-decision --command 'echo should-not-run' --timeout 30 >/dev/null 2>"$TMP/decision.err"
DECISION_RC=$?
set -e
[[ "$DECISION_RC" -eq 3 ]]
grep -q 'WAITING_FOR_DECISION' "$TMP/decision.err"
! grep -q 'blocked-by-decision' "$PROJECT/.paper-repro/system/SYSTEM_ISSUES.md"
python "$ROOT/scripts/reproctl.py" decisions resolve "$DECISION_ID" --option main --remember workspace --note 'smoke' >/dev/null
python "$ROOT/scripts/reproctl.py" decisions assess \
  --title '再次选择实验覆盖范围' --question '沿用已确认的实验范围？' \
  --category experiment-scope --stage execution --impact high --reversibility reversible --confidence 0.9 --changes-results \
  --options-json '[{"id":"main","label":"只复现主表","recommended":true},{"id":"all","label":"主表与消融"}]' \
  --default-option main --recommended-option main --preference-key experiment.scope > "$TMP/remembered.json"
python - "$TMP/remembered.json" <<'PY'
import json, sys
item=json.load(open(sys.argv[1], encoding='utf-8'))
assert item['requires_user'] is False
assert item['selected_option'] == 'main'
assert item['handling'] == '应用已记住的偏好'
PY
DECISION_RUN="$(readlink -f "$PROJECT/.paper-repro/current")"
test -f "$DECISION_RUN/report/DECISIONS.md"
grep -q '选择实验覆盖范围' "$DECISION_RUN/report/DECISIONS.md"

SERVE="$TMP/serve"
mkdir -p "$SERVE"
dd if=/dev/urandom of="$SERVE/blob.bin" bs=1024 count=256 status=none
PORT="$(python - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
)"
python -m http.server "$PORT" --bind 127.0.0.1 --directory "$SERVE" >"$TMP/http.log" 2>&1 &
SERVER_PID=$!
sleep 1
python "$ROOT/scripts/reproctl.py" download \
  --url "http://127.0.0.1:$PORT/blob.bin" \
  --output data/blob.bin --stage assets >/dev/null
cmp "$SERVE/blob.bin" "$PROJECT/data/blob.bin"

set +e
python "$ROOT/scripts/reproctl.py" exec --stage expected-failure --command 'exit 9' --timeout 30 >/dev/null 2>&1
RC=$?
set -e
[[ "$RC" -eq 9 ]]

RUN_DIR="$(readlink -f "$PROJECT/.paper-repro/current")"
test -f "$RUN_DIR/report/RUN_BLOCKERS.md"
grep -q 'expected-failure' "$RUN_DIR/report/RUN_BLOCKERS.md"
! grep -q 'expected-failure' "$PROJECT/.paper-repro/system/SYSTEM_ISSUES.md"

python "$ROOT/scripts/reproctl.py" code index >/dev/null
test -f "$RUN_DIR/analysis/code_index.json"
grep -q 'main.py' "$RUN_DIR/report/code-guide/STATIC_STRUCTURE.md"

python "$ROOT/scripts/reproctl.py" issue add --title 'smoke-system' --details 'system feedback test' --category testing >/dev/null
grep -q 'smoke-system' "$PROJECT/.paper-repro/system/SYSTEM_ISSUES.md"
python "$ROOT/scripts/reproctl.py" feedback >/dev/null
FEEDBACK="$(find "$PROJECT/.paper-repro/system/feedback" -name '*.zip' -type f | head -1)"
unzip -l "$FEEDBACK" | grep -q 'SYSTEM_ISSUES.md'
! unzip -l "$FEEDBACK" | grep -q 'RUN_BLOCKERS.md'

python "$ROOT/scripts/reproctl.py" status > "$TMP/status.zh.txt"
grep -q '论文代码复现状态' "$TMP/status.zh.txt"
grep -q '项目复现阻塞项' "$TMP/status.zh.txt"


export PAPER_REPRO_CONFIG_HOME="$TMP/paper-repro-config"
export PAPER_REPRO_CONFIG_FILE="$PAPER_REPRO_CONFIG_HOME/config.json"
# Drop caller-injected secret environment variables so the persisted-value
# assertions below are deterministic (apply_persistent_secrets never overwrites).
unset PAPER_VISION_API_KEY CONTEXT7_API_KEY GITHUB_MCP_TOKEN GITHUB_TOKEN HF_TOKEN HUGGING_FACE_HUB_TOKEN BRAVE_API_KEY BRAVE_API_KEY_FILE GITHUB_PUBLISH_TOKEN 2>/dev/null || true
python "$ROOT/scripts/reproctl.py" secrets init --quiet
printf 'smoke-vision-token' | python "$ROOT/scripts/reproctl.py" secrets set PAPER_VISION_API_KEY --stdin >/dev/null
python "$ROOT/scripts/reproctl.py" secrets exec -- python -c 'import os; assert os.environ["PAPER_VISION_API_KEY"] == "smoke-vision-token"'
[[ "$(stat -c '%a' "$PAPER_REPRO_CONFIG_FILE")" == "600" ]]
python "$ROOT/scripts/reproctl.py" --workspace "$PROJECT" models profile set --name smoke-vision --base-url https://example.invalid/v1 --model smoke-vl --api-key-env PAPER_VISION_API_KEY >/dev/null
python "$ROOT/scripts/reproctl.py" --workspace "$PROJECT" models route --task table --profile smoke-vision >/dev/null
python "$ROOT/scripts/reproctl.py" mcp install-basic --quiet
python "$ROOT/scripts/reproctl.py" mcp status > "$TMP/mcp-status.json"
python - "$TMP/mcp-status.json" <<'PY'
import json, sys
data=json.load(open(sys.argv[1], encoding="utf-8"))
assert data["native_websearch"]["enabled"] is True
servers={x["name"]:x for x in data["servers"]}
assert servers["context7"]["enabled"] is True
assert servers["github-readonly"]["enabled"] is False
PY
python "$ROOT/scripts/reproctl.py" mcp enable github-readonly >/dev/null
grep -q 'github-readonly' "$PAPER_REPRO_CONFIG_HOME/opencode.mcp.runtime.json"
python - "$PAPER_REPRO_CONFIG_FILE" <<'PY'
import json, sys
data=json.load(open(sys.argv[1], encoding="utf-8"))
assert data["secrets"]["PAPER_VISION_API_KEY"] == "smoke-vision-token"
assert data["model_routing"]["profiles"]["smoke-vision"]["model"] == "smoke-vl"
assert data["mcp"]["servers"]["github-readonly"]["enabled"] is True
PY
python "$ROOT/scripts/reproctl.py" secrets clear --yes >/dev/null
python - "$PAPER_REPRO_CONFIG_FILE" <<'PY'
import json, sys
data=json.load(open(sys.argv[1], encoding="utf-8"))
assert data["secrets"] == {}
assert data["model_routing"]["profiles"]
assert data["mcp"]["servers"]
PY

if [[ "${PAPER_REPRO_SELF_TEST:-0}" != "1" ]]; then
  export PAPER_REPRO_SOURCE_HOME="$ROOT"
  python "$ROOT/scripts/reproctl.py" improve policy set --mode guarded --no-require-smoke-tests >/dev/null
  python "$ROOT/scripts/reproctl.py" improve submit \
    --title '自我迭代冒烟测试' --details '在隔离副本中增加一份测试文档' > "$TMP/improvement.json"
  IMPROVEMENT_ID="$(python - "$TMP/improvement.json" <<'PYID'
import json, sys
print(json.load(open(sys.argv[1], encoding='utf-8'))['improvement_id'])
PYID
)"
  python "$ROOT/scripts/reproctl.py" improve prepare "$IMPROVEMENT_ID" >/dev/null
  python "$ROOT/scripts/reproctl.py" improve write "$IMPROVEMENT_ID" \
    --path docs/SELF_IMPROVEMENT_SMOKE.md --content 'isolated self-improvement smoke' >/dev/null
  python "$ROOT/scripts/reproctl.py" improve test "$IMPROVEMENT_ID" > "$TMP/improvement-test.json"
  python - "$TMP/improvement-test.json" <<'PYTEST'
import json, sys
item=json.load(open(sys.argv[1], encoding='utf-8'))
assert item['passed'] is True
assert item['classification']['risk'] == 'low'
assert item['classification']['auto_apply_eligible'] is True
PYTEST
  python "$ROOT/scripts/reproctl.py" improve propose "$IMPROVEMENT_ID" >/dev/null
  python "$ROOT/scripts/reproctl.py" improve status "$IMPROVEMENT_ID" > "$TMP/improvement-status.json"
  python - "$TMP/improvement-status.json" <<'PYSTATUS'
import json, sys
item=json.load(open(sys.argv[1], encoding='utf-8'))
assert item['status'] == 'proposed'
assert item['tests_passed'] is True
PYSTATUS
fi


# Privacy-preserving GitHub publication: clean source snapshot, exact persisted-secret scan,
# explicit repository/visibility approval, and a mocked GitHub push with a fresh history.
if [[ "${PAPER_REPRO_SELF_TEST:-0}" != "1" ]]; then
  export PAPER_REPRO_SOURCE_HOME="$ROOT"
  python "$ROOT/scripts/reproctl.py" publish configure \
    --owner smoke-owner --repository paper-repro-public --visibility private \
    --description 'publication smoke' --license MIT --copyright-holder 'Smoke Owner' \
    --auth-method gh --existing-repo-mode pull-request --sync-mode managed-mirror --after-verified notify >/dev/null
  SECRET_VALUE="$(printf 'smoke-%s-%s' private 123456789)"
  python "$ROOT/scripts/reproctl.py" secrets set TEST_PUBLISH_SECRET --value "$SECRET_VALUE" >/dev/null
  python "$ROOT/scripts/reproctl.py" publish prepare --scan > "$TMP/publish-prepare.json"
  PUB_LEAK="$(python - "$TMP/publish-prepare.json" <<'PYPUB'
import json, sys
print(json.load(open(sys.argv[1], encoding='utf-8'))['publication_id'])
PYPUB
)"
  python - "$TMP/publish-prepare.json" <<'PYCLEAN'
import json, sys
item=json.load(open(sys.argv[1], encoding='utf-8'))
assert item['scan']['passed'] is True
PYCLEAN
  SNAPSHOT="$(python - "$TMP/publish-prepare.json" <<'PYSNAP'
import json, sys
print(json.load(open(sys.argv[1], encoding='utf-8'))['snapshot'])
PYSNAP
)"
  printf '%s\n' "$SECRET_VALUE" > "$SNAPSHOT/LEAK.txt"
  python "$ROOT/scripts/reproctl.py" publish scan "$PUB_LEAK" > "$TMP/publish-leak-scan.json"
  python - "$TMP/publish-leak-scan.json" <<'PYLEAK'
import json, sys
item=json.load(open(sys.argv[1], encoding='utf-8'))
assert item['passed'] is False
assert any(x['type'] == 'known-secret' for x in item['blocking_findings'])
PYLEAK
  python "$ROOT/scripts/reproctl.py" publish abort "$PUB_LEAK" --delete-session --reason 'expected leak test' >/dev/null
  python "$ROOT/scripts/reproctl.py" secrets unset TEST_PUBLISH_SECRET >/dev/null

  FAKE_GH_HOME="$TMP/fake-gh"
  FAKE_GH_BIN="$FAKE_GH_HOME/bin"
  mkdir -p "$FAKE_GH_BIN" "$FAKE_GH_HOME/remote"
  export FAKE_GH_REMOTE="$FAKE_GH_HOME/remote/repo.git"
  export FAKE_GH_MARKER="$FAKE_GH_HOME/remote/exists"
  cat > "$FAKE_GH_BIN/gh" <<'GHMOCK'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-} ${2:-}" in
  "auth status") echo 'Logged in'; exit 0 ;;
  "repo view") [[ -f "$FAKE_GH_MARKER" ]] && { echo '{"nameWithOwner":"smoke-owner/paper-repro-public","isPrivate":true,"visibility":"PRIVATE","url":"https://github.com/smoke-owner/paper-repro-public","defaultBranchRef":{"name":"main"}}'; exit 0; } || exit 1 ;;
  "repo create") git init --bare --initial-branch=main "$FAKE_GH_REMOTE" >/dev/null; touch "$FAKE_GH_MARKER"; echo 'https://github.com/smoke-owner/paper-repro-public'; exit 0 ;;
  "repo clone") git clone "$FAKE_GH_REMOTE" "${4}" >/dev/null 2>&1; exit 0 ;;
  "repo edit") exit 0 ;;
  "pr create") echo 'https://github.com/smoke-owner/paper-repro-public/pull/1'; exit 0 ;;
esac
echo "unsupported fake gh: $*" >&2
exit 2
GHMOCK
  chmod +x "$FAKE_GH_BIN/gh"
  export PATH="$FAKE_GH_BIN:$PATH"
  python "$ROOT/scripts/reproctl.py" publish prepare --scan > "$TMP/publish-clean.json"
  PUB_OK="$(python - "$TMP/publish-clean.json" <<'PYOK'
import json, sys
print(json.load(open(sys.argv[1], encoding='utf-8'))['publication_id'])
PYOK
)"
  python "$ROOT/scripts/reproctl.py" publish approve "$PUB_OK" \
    --confirm 'PUBLISH smoke-owner/paper-repro-public AS private' >/dev/null
  python "$ROOT/scripts/reproctl.py" publish push "$PUB_OK" > "$TMP/publish-result.json"
  python - "$TMP/publish-result.json" <<'PYPUSH'
import json, sys
item=json.load(open(sys.argv[1], encoding='utf-8'))
assert item['status'] == 'published'
assert item['repository'] == 'smoke-owner/paper-repro-public'
PYPUSH
  git clone "$FAKE_GH_REMOTE" "$TMP/published-check" >/dev/null 2>&1
  test -f "$TMP/published-check/PRIVACY.md"
  test -f "$TMP/published-check/SECURITY.md"
  test -f "$TMP/published-check/LICENSE"
  test ! -e "$TMP/published-check/.paper-repro"
  ! find "$TMP/published-check" -name '*.pdf' -o -name '*.ckpt' | grep -q .
fi

echo "smoke test passed"
