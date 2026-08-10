#!/usr/bin/env python3
import json
import tempfile
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import runtime_engine as rte  # noqa: E402


def fake_gpus():
    return [
        {"index": 0, "name": "Fake0", "uuid": "GPU-0", "util_gpu_pct": 0, "memory_used_mb": 0, "memory_free_mb": 24576, "memory_total_mb": 24576, "temperature_c": 40, "power_w": 20},
        {"index": 1, "name": "Fake1", "uuid": "GPU-1", "util_gpu_pct": 0, "memory_used_mb": 0, "memory_free_mb": 24576, "memory_total_mb": 24576, "temperature_c": 41, "power_w": 21},
    ]


def main():
    original = rte.parse_nvidia_smi
    rte.parse_nvidia_smi = fake_gpus
    try:
        with tempfile.TemporaryDirectory(prefix="paper-repro-runtime-test-") as td:
            run = Path(td) / "runs" / "run-test"
            (run / "meta").mkdir(parents=True)
            (run / "execution" / "logs").mkdir(parents=True)
            (run / "meta" / "state.json").write_text(json.dumps({"status":"running","stage":"execution","pipeline":{"steps":[]}}))
            paths = rte.RuntimePaths(run)
            paths.ensure()

            policy = rte.default_gpu_policy()
            assert policy["configured"] is False
            policy["allowed_gpu_ids"] = [0, 1]
            policy["scheduler"]["max_parallel_tasks"] = 2
            rte.save_gpu_policy(paths, policy)

            env = {"name":"proj","prefix":"/tmp/proj"}
            a = rte.add_task(paths, display_name="A", stage="execution", command="echo A", workspace=td, execution_env=env, gpu_count=1, task_id="A")
            b = rte.add_task(paths, display_name="B", stage="execution", command="echo B", workspace=td, execution_env=env, gpu_count=1, task_id="B")
            assert rte._candidate_gpus(paths, a, rte.read_tasks(paths)) == [0]
            rte.update_task(paths, "A", state="running", gpu_ids=[0], worker_pid=999999)
            assert rte._candidate_gpus(paths, b, rte.read_tasks(paths)) == [1]

            try:
                rte.add_task(paths, display_name="bad", stage="execution", command="echo bad", workspace=td, execution_env=env, gpu_count=1, gpu_ids=[2], task_id="BAD")
                raise AssertionError("GPU outside approved pool was accepted")
            except rte.RuntimeErrorEx:
                pass

            start = time.time() - 10
            p = rte._progress_from_line(" 42%|####      | 42/100 [00:10<00:14]", {"type":"tqdm"}, start)
            assert p and p["current"] == 42 and p["total"] == 100 and p["source"] == "tqdm"
            p = rte._progress_from_line("REPRO_PROGRESS 7/20 sample", {"type":"native"}, start)
            assert p and p["current"] == 7 and p["total"] == 20 and p["source"] == "native-REPRO_PROGRESS"

            evt = rte.emit_event(paths, "task.progress", task_id="A", data={"current": 7, "total": 20})
            events = rte.read_events_after(paths, None)
            assert any(x["event_id"] == evt["event_id"] for x in events)
            page = rte.read_events_page(paths, None, limit=1)
            assert page["cursor_found"] is True
            assert len(page["events"]) == 1
            assert page["next_cursor"].startswith("EVT-")
            missing = rte.read_events_page(paths, "EVT-999999999999", limit=10)
            assert missing["cursor_found"] is False
            assert missing["events"] == []

            snap = rte.refresh_snapshot(paths)
            assert snap["queue"]["total"] == 2
            assert snap["gpu"]["assignments"].get("0") == ["A"]
            print("RUNTIME_ENGINE_TEST_OK")
    finally:
        rte.parse_nvidia_smi = original


if __name__ == "__main__":
    main()
