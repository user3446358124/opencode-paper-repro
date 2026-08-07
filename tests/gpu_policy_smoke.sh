#!/usr/bin/env bash
# Minimal GPU-policy regression: fake nvidia-smi + a few direct assertions.
# Covers: auto avoids already-allocated cards, no-GPU fallback, explicit
# CUDA_VISIBLE_DEVICES override, utilization tie-break, all-excluded fallback.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

FAKE_BIN="$TMP/bin"
mkdir -p "$FAKE_BIN"

# Three GPUs: 0 (1024 MiB, 10%), 1 (2048 MiB, 90%), 2 (3000 MiB, 5%).
# GPU 0 has the least memory, so auto-selection prefers it unless excluded.
cat > "$FAKE_BIN/nvidia-smi" <<'SMIMOCK'
#!/usr/bin/env bash
if [[ "${1:-}" == "-q" ]]; then
  echo "fake nvidia-smi"
  exit 0
fi
cat <<'CSV'
0, NVIDIA A100-PCIE-40GB, GPU-00000000-0000-0000-0000-000000000000, 10, 1024, 40960, 28, 35
1, NVIDIA A100-PCIE-40GB, GPU-00000000-0000-0000-0000-000000000001, 90, 2048, 40960, 28, 36
2, NVIDIA A100-PCIE-40GB, GPU-00000000-0000-0000-0000-000000000002, 5, 3000, 40960, 28, 37
CSV
SMIMOCK
chmod +x "$FAKE_BIN/nvidia-smi"

# Isolate from the caller (repro_* inject REPRO_WORKSPACE / CONDA_EXE).
unset REPRO_WORKSPACE REPRO_STATE_HOME REPRO_RUN_DIR CONDA_EXE PAPER_REPRO_CONDA_EXE 2>/dev/null || true
export PATH="$FAKE_BIN:$PATH"

python - "$ROOT" <<'PY'
import os
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(root / "scripts"))

import gpu_policy  # noqa: E402
import reproctl  # noqa: E402

# Sanity: the fake nvidia-smi is really used by gpu_rows().
rows = reproctl.gpu_rows()
assert [r["index"] for r in rows] == ["0", "1", "2"], rows

# 1) auto with an exclude set avoids the card already allocated by the run.
value, note = gpu_policy.resolve_gpus("auto", "python train.py", reproctl.gpu_rows, exclude=["0"])
assert value == "1", (value, note)
assert "避开" in note, note

# 2) no GPU available: nothing is set.
saved_path = os.environ.get("PATH", "")
os.environ["PATH"] = "/nonexistent"
try:
    assert reproctl.gpu_rows() == []
    value, note = gpu_policy.resolve_gpus("auto", "python train.py", reproctl.gpu_rows)
finally:
    os.environ["PATH"] = saved_path
assert value is None, (value, note)

# 3) an explicit CUDA_VISIBLE_DEVICES=... in the command is never overridden.
value, note = gpu_policy.resolve_gpus("auto", "CUDA_VISIBLE_DEVICES=1 python train.py", reproctl.gpu_rows)
assert value is None and "未覆盖" in note, (value, note)

# 4) utilization tie-break: same memory, lower utilization wins.
tie_rows = [
    {"index": "0", "memory_used_mb": "1024", "util_gpu_pct": "90"},
    {"index": "1", "memory_used_mb": "1024", "util_gpu_pct": "10"},
]
value, note = gpu_policy.resolve_gpus("auto", "python train.py", lambda: tie_rows)
assert value == "1", (value, note)

# 5) every card excluded: fall back instead of deadlocking.
value, note = gpu_policy.resolve_gpus("auto", "python train.py", reproctl.gpu_rows, exclude=["0", "1", "2"])
assert value is not None, (value, note)

# 6) recent_gpu_allocations: only still-running commands count (start adds, finish removes).
import json as _json
import tempfile as _tempfile
with _tempfile.TemporaryDirectory() as _d:
    _run_dir = pathlib.Path(_d) / "run"
    _cmd = _run_dir / "execution" / "commands.jsonl"
    _cmd.parent.mkdir(parents=True)
    _cmd.write_text(
        _json.dumps({"record_type": "start", "id": "a", "gpus_index": "0"}) + "\n"
        + _json.dumps({"record_type": "start", "id": "b", "gpus_index": "1"}) + "\n"
        + _json.dumps({"record_type": "finish", "id": "a"}) + "\n",
        encoding="utf-8",
    )
    assert reproctl.recent_gpu_allocations(reproctl.RunPaths(_run_dir)) == ["1"]

# 7) configured_gpus_default: config value wins, missing config falls back to auto.
with _tempfile.TemporaryDirectory() as _d:
    _ws = pathlib.Path(_d) / "ws"
    (_ws / ".paper-repro").mkdir(parents=True)
    (_ws / ".paper-repro" / "config.json").write_text(
        _json.dumps({"execution_env": {"gpus_default": "0,1"}}), encoding="utf-8")
    _paths = reproctl.WorkspacePaths(workspace=_ws, state_home=_ws / ".paper-repro")
    assert reproctl.configured_gpus_default(_paths) == "0,1"
    _ws2 = pathlib.Path(_d) / "empty"
    _ws2.mkdir()
    _paths2 = reproctl.WorkspacePaths(workspace=_ws2, state_home=_ws2 / ".paper-repro")
    assert reproctl.configured_gpus_default(_paths2) == "auto"

print("gpu_policy smoke passed")
PY
