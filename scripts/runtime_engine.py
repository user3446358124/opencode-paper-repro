#!/usr/bin/env python3
"""Persistent execution runtime for paper-repro.

This module deliberately contains no OpenCode-specific logic. It owns task semantics,
GPU allocation, progress/ETA, queue handoff, and machine-readable runtime state.
OpenCode submits plans; the scheduler keeps running independently of the agent session.
"""
from __future__ import annotations

import contextlib
import fcntl
import itertools
import json
import math
import os
import re
import select
import shlex
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import security as sec

sec.secure_umask()

SCHEMA_VERSION = 1
TERMINAL_STATES = {"succeeded", "failed", "timeout", "cancelled", "blocked", "skipped"}
ACTIVE_STATES = {"starting", "running"}
QUEUE_STATES = {"queued", "waiting-resources", "waiting-dependencies"}

NATIVE_PROGRESS_RE = re.compile(r"REPRO_PROGRESS\s+(?P<current>\d+(?:\.\d+)?)/(?P<total>\d+(?:\.\d+)?)\s*(?P<message>.*)")
# Handles common tqdm forms, including CR-updated progress bars.
TQDM_RE = re.compile(
    r"(?P<percent>\d{1,3})%\|[^|]*\|\s*(?P<current>\d+(?:\.\d+)?)/(?P<total>\d+(?:\.\d+)?)"
    r"(?:\s*\[(?P<elapsed>[^<\],]+)<(?P<eta>[^\],]+)(?:,\s*(?P<rate>[^\]]+))?\])?"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _atomic_json(path: Path, data: Any, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)
    if mode is not None:
        os.chmod(path, mode)


def _append_jsonl(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def redact(text: str) -> str:
    return sec.redact_text(text)


class RuntimeErrorEx(RuntimeError):
    pass


class RuntimePaths:
    def __init__(self, run_root: str | Path):
        self.run_root = Path(run_root).resolve()
        self.runtime = self.run_root / "runtime"
        self.tasks = self.runtime / "tasks.json"
        self.specs = self.runtime / "task-specs.json"
        self.events = self.runtime / "task-events.jsonl"
        self.remote_events = self.runtime / "remote-events.jsonl"
        self.event_seq = self.runtime / "event-seq.txt"
        self.lock = self.runtime / "runtime.lock"
        self.scheduler = self.runtime / "scheduler.json"
        self.scheduler_pid = self.runtime / "scheduler.pid"
        self.scheduler_log = self.runtime / "scheduler.log"
        self.gpu_policy = self.runtime / "gpu-policy.json"
        self.plan = self.runtime / "execution-plan.json"
        self.snapshot = self.runtime / "snapshot.json"
        self.state = self.run_root / "meta" / "state.json"
        self.logs = self.run_root / "execution" / "logs"
        self.commands = self.run_root / "execution" / "commands.jsonl"

    def ensure(self) -> None:
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        if not self.tasks.exists():
            _atomic_json(self.tasks, {"schema_version": SCHEMA_VERSION, "updated_at": utc_now(), "tasks": []})
        if not self.specs.exists():
            _atomic_json(self.specs, {"schema_version": SCHEMA_VERSION, "updated_at": utc_now(), "specs": {}}, mode=0o600)
        if not self.scheduler.exists():
            _atomic_json(self.scheduler, {
                "schema_version": SCHEMA_VERSION,
                "state": "stopped",
                "pid": None,
                "started_at": None,
                "updated_at": utc_now(),
                "last_error": None,
            })


@contextlib.contextmanager
def runtime_lock(paths: RuntimePaths):
    paths.ensure()
    fd = os.open(paths.lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def read_tasks(paths: RuntimePaths) -> list[dict[str, Any]]:
    paths.ensure()
    data = _read_json(paths.tasks, {"tasks": []})
    return list(data.get("tasks") or [])


def read_specs(paths: RuntimePaths) -> dict[str, Any]:
    paths.ensure()
    data = _read_json(paths.specs, {"specs": {}})
    return dict(data.get("specs") or {})


def _write_tasks_locked(paths: RuntimePaths, tasks: list[dict[str, Any]]) -> None:
    _atomic_json(paths.tasks, {"schema_version": SCHEMA_VERSION, "updated_at": utc_now(), "tasks": tasks})


def _write_specs_locked(paths: RuntimePaths, specs: dict[str, Any]) -> None:
    _atomic_json(paths.specs, {"schema_version": SCHEMA_VERSION, "updated_at": utc_now(), "specs": specs}, mode=0o600)


def _next_event_id_locked(paths: RuntimePaths) -> str:
    """Allocate a run-scoped monotonic event ID without reusing IDs after seq-file loss."""
    seq: int | None = None
    try:
        seq = int(paths.event_seq.read_text(encoding="utf-8").strip() or "0")
    except (FileNotFoundError, ValueError):
        seq = None
    if seq is None:
        seq = 0
        for source in (paths.remote_events, paths.events):
            if not source.exists():
                continue
            try:
                for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
                    try:
                        event_id = str(json.loads(line).get("event_id") or "")
                    except json.JSONDecodeError:
                        continue
                    match = re.fullmatch(r"EVT-(\d+)", event_id)
                    if match:
                        seq = max(seq, int(match.group(1)))
            except OSError:
                continue
    seq += 1
    fd = os.open(paths.event_seq, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, str(seq).encode("utf-8"))
    finally:
        os.close(fd)
    return f"EVT-{seq:012d}"


def emit_event(paths: RuntimePaths, event_type: str, *, run_id: str | None = None, task_id: str | None = None, data: dict[str, Any] | None = None) -> dict[str, Any]:
    with runtime_lock(paths):
        event_id = _next_event_id_locked(paths)
        record = {
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id,
            "type": event_type,
            "ts": utc_now(),
            "run_id": run_id or paths.run_root.name,
            "task_id": task_id,
            "data": data or {},
        }
        _append_jsonl(paths.events, record)
        _append_jsonl(paths.remote_events, record)
    return record


def task_by_id(paths: RuntimePaths, task_id: str) -> dict[str, Any] | None:
    return next((t for t in read_tasks(paths) if t.get("task_id") == task_id), None)


def update_task(paths: RuntimePaths, task_id: str, **changes: Any) -> dict[str, Any]:
    with runtime_lock(paths):
        tasks = read_tasks(paths)
        found = None
        for idx, task in enumerate(tasks):
            if task.get("task_id") == task_id:
                updated = dict(task)
                # Merge nested progress rather than replacing accidental fields.
                update_ts = utc_now()
                if isinstance(changes.get("progress"), dict):
                    prog = dict(updated.get("progress") or {})
                    prog.update(changes.pop("progress"))
                    prog["updated_at"] = update_ts
                    updated["progress"] = prog
                updated.update(changes)
                updated["updated_at"] = update_ts
                tasks[idx] = updated
                found = updated
                break
        if found is None:
            raise RuntimeErrorEx(f"Unknown task: {task_id}")
        _write_tasks_locked(paths, tasks)
    return found


def add_task(
    paths: RuntimePaths,
    *,
    display_name: str,
    stage: str,
    command: str,
    workspace: str,
    execution_env: dict[str, Any],
    timeout_seconds: int = 86400,
    estimate_seconds: int = 0,
    gpu_count: int = 1,
    gpu_ids: list[int] | None = None,
    min_free_memory_mb: int = 0,
    priority: int = 0,
    dependencies: list[str] | None = None,
    parallel_group_id: str | None = None,
    progress_adapter: dict[str, Any] | None = None,
    output_paths: list[str] | None = None,
    task_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    sandbox_policy: dict[str, Any] | None = None,
    secret_env: list[str] | None = None,
) -> dict[str, Any]:
    paths.ensure()
    task_id = task_id or f"TASK-{uuid.uuid4().hex[:12]}"
    dependencies = dependencies or []
    preferred_gpu_ids = list(gpu_ids or [])
    if len(set(preferred_gpu_ids)) != len(preferred_gpu_ids):
        raise RuntimeErrorEx("gpu_ids must be unique")
    if any(int(idx) < 0 for idx in preferred_gpu_ids):
        raise RuntimeErrorEx("gpu_ids must be non-negative")
    policy = load_gpu_policy(paths)
    if int(max(0, gpu_count)) > 0 and policy.get("configured") and preferred_gpu_ids:
        allowed = {int(x) for x in policy.get("allowed_gpu_ids") or []}
        outside = sorted(set(int(x) for x in preferred_gpu_ids) - allowed)
        if outside:
            raise RuntimeErrorEx(
                f"Task requests GPU(s) outside the user-approved pool: {outside}; approved={sorted(allowed)}"
            )
        if len(preferred_gpu_ids) < int(max(0, gpu_count)):
            raise RuntimeErrorEx("Explicit gpu_ids must contain at least gpu_count devices")
    now_ts = utc_now()
    public_task = {
        "task_id": task_id,
        "display_name": display_name,
        "stage": stage,
        "state": "queued",
        "command": redact(command),
        "cwd": str(Path(workspace).resolve()),
        "project_env": {
            "name": execution_env.get("name"),
            "prefix": execution_env.get("prefix"),
        },
        "gpu_request": {
            "count": int(max(0, gpu_count)),
            "preferred_ids": preferred_gpu_ids,
            "min_free_memory_mb": int(max(0, min_free_memory_mb)),
        },
        "gpu_ids": [],
        "launcher_pid": None,
        "worker_pid": None,
        "started_at": None,
        "finished_at": None,
        "created_at": now_ts,
        "updated_at": now_ts,
        "progress": {
            "current": 0,
            "total": None,
            "unit": str((progress_adapter or {}).get("unit", "item")),
            "percent": 0.0,
            "speed": None,
            "speed_unit": None,
            "eta_seconds": None,
            "eta_confidence": "unknown",
            "eta_source": None,
            "estimated_finish_at": None,
            "source": "unknown",
            "updated_at": now_ts,
            "message": "等待调度",
        },
        "log_path": None,
        "output_paths": list(output_paths or []),
        "parent_task_id": None,
        "parallel_group_id": parallel_group_id,
        "dependencies": list(dependencies),
        "priority": int(priority),
        "error": None,
        "exit_code": None,
        "timeout_seconds": int(timeout_seconds),
        "estimate_seconds": int(estimate_seconds) if estimate_seconds > 0 else None,
        "metadata": metadata or {},
        "sandbox": {"mode": str((sandbox_policy or {}).get("mode", "auto")), "backend": str((sandbox_policy or {}).get("backend", "auto"))},
        "secret_env": list(secret_env or []),
    }
    private_spec = {
        "task_id": task_id,
        "command": command,
        "workspace": str(Path(workspace).resolve()),
        "execution_env": execution_env,
        "timeout_seconds": int(timeout_seconds),
        "estimate_seconds": int(estimate_seconds),
        "progress_adapter": progress_adapter or {"type": "auto"},
        "output_paths": list(output_paths or []),
        "env": {},
        "sandbox": dict(sandbox_policy or {"mode": "auto", "backend": "auto", "network": "on"}),
        "secret_env": list(secret_env or []),
    }
    with runtime_lock(paths):
        tasks = read_tasks(paths)
        if any(t.get("task_id") == task_id for t in tasks):
            raise RuntimeErrorEx(f"Task id already exists: {task_id}")
        tasks.append(public_task)
        specs = read_specs(paths)
        specs[task_id] = private_spec
        _write_tasks_locked(paths, tasks)
        _write_specs_locked(paths, specs)
    emit_event(paths, "task.created", task_id=task_id, data={
        "display_name": display_name,
        "stage": stage,
        "gpu_request": public_task["gpu_request"],
        "parallel_group_id": parallel_group_id,
    })
    refresh_snapshot(paths)
    return public_task


def save_plan(paths: RuntimePaths, plan: dict[str, Any]) -> dict[str, Any]:
    paths.ensure()
    plan = dict(plan)
    plan.setdefault("schema_version", SCHEMA_VERSION)
    plan.setdefault("created_at", utc_now())
    plan["updated_at"] = utc_now()
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise RuntimeErrorEx("Execution plan requires a non-empty tasks list")
    ids: set[str] = set()
    for item in tasks:
        if not isinstance(item, dict):
            raise RuntimeErrorEx("Each execution-plan task must be an object")
        tid = str(item.get("task_id", "")).strip() or f"TASK-{uuid.uuid4().hex[:12]}"
        if tid in ids:
            raise RuntimeErrorEx(f"Duplicate task_id in execution plan: {tid}")
        ids.add(tid)
        item["task_id"] = tid
        if not str(item.get("display_name", "")).strip() or not str(item.get("command", "")).strip():
            raise RuntimeErrorEx(f"Task {tid} requires display_name and command")
        item.setdefault("stage", "execution")
        item.setdefault("gpu_count", 1)
        item.setdefault("priority", 0)
        item.setdefault("dependencies", [])
        item.setdefault("progress_adapter", {"type": "auto"})
    for item in tasks:
        unknown = [dep for dep in item.get("dependencies", []) if dep not in ids]
        if unknown:
            raise RuntimeErrorEx(f"Task {item['task_id']} has unknown dependencies: {unknown}")
    _atomic_json(paths.plan, plan)
    emit_event(paths, "plan.created", data={"task_count": len(tasks), "plan_path": "runtime/execution-plan.json"})
    return plan


def submit_plan(paths: RuntimePaths, plan: dict[str, Any], execution_env: dict[str, Any], workspace: str) -> list[dict[str, Any]]:
    saved = save_plan(paths, plan)
    created = []
    for item in saved["tasks"]:
        created.append(add_task(
            paths,
            task_id=item["task_id"],
            display_name=str(item["display_name"]),
            stage=str(item.get("stage", "execution")),
            command=str(item["command"]),
            workspace=workspace,
            execution_env=execution_env,
            timeout_seconds=int(item.get("timeout_seconds", 86400)),
            estimate_seconds=int(item.get("estimate_seconds", 0) or 0),
            gpu_count=int(item.get("gpu_count", 1) or 0),
            gpu_ids=[int(x) for x in item.get("gpu_ids", [])],
            min_free_memory_mb=int(item.get("min_free_memory_mb", 0) or 0),
            priority=int(item.get("priority", 0) or 0),
            dependencies=list(item.get("dependencies", [])),
            parallel_group_id=item.get("parallel_group_id"),
            progress_adapter=dict(item.get("progress_adapter") or {"type": "auto"}),
            output_paths=list(item.get("output_paths", [])),
            metadata=dict(item.get("metadata") or {}),
            sandbox_policy=dict(item.get("sandbox") or plan.get("sandbox") or {"mode":"auto","backend":"auto","network":"on"}),
            secret_env=list(item.get("secret_env") or []),
        ))
    return created


def parse_nvidia_smi() -> list[dict[str, Any]]:
    if not shutil_which("nvidia-smi"):
        return []
    query = "index,name,uuid,utilization.gpu,memory.used,memory.free,memory.total,temperature.gpu,power.draw"
    try:
        proc = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    keys = ["index", "name", "uuid", "util_gpu_pct", "memory_used_mb", "memory_free_mb", "memory_total_mb", "temperature_c", "power_w"]
    numeric = {"index", "util_gpu_pct", "memory_used_mb", "memory_free_mb", "memory_total_mb", "temperature_c", "power_w"}
    rows: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        values = [x.strip() for x in line.split(",")]
        if len(values) != len(keys):
            continue
        row: dict[str, Any] = {}
        for k, v in zip(keys, values):
            if k in numeric:
                try:
                    row[k] = float(v) if "." in v else int(v)
                except ValueError:
                    row[k] = None
            else:
                row[k] = v
        rows.append(row)
    return rows


def shutil_which(name: str) -> str | None:
    # Local helper avoids importing shutil only for one call in hot polling loops.
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(folder) / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def default_gpu_policy() -> dict[str, Any]:
    visible = [int(row["index"]) for row in parse_nvidia_smi() if row.get("index") is not None]
    return {
        "schema_version": SCHEMA_VERSION,
        "configured": False,
        "allowed_gpu_ids": visible,
        "cpu_allowed": True,
        "confirm_each_run": True,
        "selection_source": "detected-default",
        "configured_at": None,
        "confirmed_at": None,
        "scheduler": {
            "policy": "fifo-best-fit",
            "max_parallel_tasks": max(1, len(visible)) if visible else 1,
            "external_busy_memory_mb": 512,
            "external_busy_util_pct": 20,
            "allow_external_busy": False,
            "poll_interval_seconds": 2.0,
            "idle_exit_seconds": 30,
        },
    }


def load_gpu_policy(paths: RuntimePaths) -> dict[str, Any]:
    base = default_gpu_policy()
    current = _read_json(paths.gpu_policy, {}) or {}
    base.update({k: v for k, v in current.items() if k != "scheduler"})
    sched = dict(base.get("scheduler") or {})
    sched.update(current.get("scheduler") or {})
    base["scheduler"] = sched
    return base


def save_gpu_policy(paths: RuntimePaths, policy: dict[str, Any]) -> dict[str, Any]:
    paths.ensure()
    data = default_gpu_policy()
    data.update({k: v for k, v in policy.items() if k != "scheduler"})
    sched = dict(data.get("scheduler") or {})
    sched.update(policy.get("scheduler") or {})
    data["scheduler"] = sched
    data["configured"] = True
    data["configured_at"] = data.get("configured_at") or utc_now()
    data["confirmed_at"] = utc_now()
    _atomic_json(paths.gpu_policy, data)
    emit_event(paths, "gpu.pool_configured", data={
        "allowed_gpu_ids": data.get("allowed_gpu_ids", []),
        "cpu_allowed": data.get("cpu_allowed", True),
        "scheduler": data.get("scheduler", {}),
    })
    refresh_snapshot(paths)
    return data


def gpu_snapshot(paths: RuntimePaths) -> dict[str, Any]:
    policy = load_gpu_policy(paths)
    telemetry = parse_nvidia_smi()
    active = [t for t in read_tasks(paths) if t.get("state") in ACTIVE_STATES]
    assignment: dict[int, list[str]] = {}
    for task in active:
        for gpu_id in task.get("gpu_ids") or []:
            assignment.setdefault(int(gpu_id), []).append(str(task.get("task_id")))
    allowed = {int(x) for x in policy.get("allowed_gpu_ids", [])}
    sched = policy.get("scheduler") or {}
    busy_mem = int(sched.get("external_busy_memory_mb", 512))
    busy_util = int(sched.get("external_busy_util_pct", 20))
    allow_external = bool(sched.get("allow_external_busy", False))
    rows: list[dict[str, Any]] = []
    for row in telemetry:
        idx = int(row.get("index", -1))
        own = assignment.get(idx, [])
        external_busy = False
        if not own:
            mem = int(row.get("memory_used_mb") or 0)
            util = int(row.get("util_gpu_pct") or 0)
            external_busy = mem >= busy_mem or util >= busy_util
        state = "not-allowed"
        if idx in allowed:
            if own:
                state = "assigned"
            elif external_busy and not allow_external:
                state = "external-busy"
            else:
                state = "available"
        rows.append({**row, "allowed": idx in allowed, "assigned_task_ids": own, "external_busy": external_busy, "scheduler_state": state})
    return {
        "policy": policy,
        "gpus": rows,
        "assignments": {str(k): v for k, v in assignment.items()},
    }


def _dependencies_ready(task: dict[str, Any], tasks: list[dict[str, Any]]) -> tuple[bool, bool]:
    deps = task.get("dependencies") or []
    if not deps:
        return True, False
    by_id = {str(t.get("task_id")): t for t in tasks}
    failed = any(by_id.get(dep, {}).get("state") in {"failed", "timeout", "cancelled", "blocked"} for dep in deps)
    ready = all(by_id.get(dep, {}).get("state") == "succeeded" for dep in deps)
    return ready, failed


def _candidate_gpus(paths: RuntimePaths, task: dict[str, Any], tasks: list[dict[str, Any]]) -> list[int] | None:
    request = task.get("gpu_request") or {}
    count = int(request.get("count", 1) or 0)
    if count == 0:
        return []
    snapshot = gpu_snapshot(paths)
    policy = snapshot["policy"]
    if not policy.get("configured"):
        return None
    preferred = [int(x) for x in request.get("preferred_ids") or []]
    allowed = [int(x) for x in policy.get("allowed_gpu_ids") or []]
    # The run-level user-approved GPU pool is a hard safety boundary.
    # A task-level affinity may narrow the pool but may never expand it.
    if preferred:
        outside = sorted(set(preferred) - set(allowed))
        if outside:
            return None
        pool = preferred
    else:
        pool = allowed
    row_by = {int(row["index"]): row for row in snapshot["gpus"] if row.get("index") is not None}
    min_free = int(request.get("min_free_memory_mb", 0) or 0)
    available = []
    for idx in pool:
        row = row_by.get(idx)
        if not row or row.get("scheduler_state") != "available":
            continue
        if int(row.get("memory_free_mb") or 0) < min_free:
            continue
        available.append(idx)
    if len(available) < count:
        return None
    # Best-fit by lower current utilization, then greater free memory.
    available.sort(key=lambda idx: (int(row_by[idx].get("util_gpu_pct") or 0), -int(row_by[idx].get("memory_free_mb") or 0), idx))
    return available[:count]


def scheduler_state(paths: RuntimePaths) -> dict[str, Any]:
    paths.ensure()
    state = _read_json(paths.scheduler, {}) or {}
    pid = state.get("pid")
    state["alive"] = bool(pid and pid_alive(int(pid)))
    if state.get("state") == "running" and not state["alive"]:
        state["state"] = "stale"
    return state


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _set_scheduler(paths: RuntimePaths, **changes: Any) -> dict[str, Any]:
    current = _read_json(paths.scheduler, {}) or {}
    current.update(changes)
    current["schema_version"] = SCHEMA_VERSION
    current["updated_at"] = utc_now()
    _atomic_json(paths.scheduler, current)
    refresh_snapshot(paths)
    return current


def start_scheduler_detached(paths: RuntimePaths, reproctl: str, workspace: str) -> dict[str, Any]:
    paths.ensure()
    current = scheduler_state(paths)
    if current.get("alive"):
        return {**current, "already_running": True}
    log = open(paths.scheduler_log, "a", encoding="utf-8")
    argv = [sys.executable, reproctl, "--workspace", workspace, "scheduler", "serve"]
    proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
    paths.scheduler_pid.write_text(str(proc.pid), encoding="utf-8")
    state = _set_scheduler(paths, state="starting", pid=proc.pid, started_at=utc_now(), last_error=None)
    emit_event(paths, "scheduler.started", data={"pid": proc.pid})
    return state


def stop_scheduler(paths: RuntimePaths, timeout: float = 5.0) -> dict[str, Any]:
    state = scheduler_state(paths)
    pid = state.get("pid")
    if pid and pid_alive(int(pid)):
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass
        deadline = time.time() + timeout
        while time.time() < deadline and pid_alive(int(pid)):
            time.sleep(0.1)
        if pid_alive(int(pid)):
            try:
                os.kill(int(pid), signal.SIGKILL)
            except OSError:
                pass
    paths.scheduler_pid.unlink(missing_ok=True)
    updated = _set_scheduler(paths, state="stopped", pid=None, stopped_at=utc_now())
    emit_event(paths, "scheduler.stopped")
    return updated


def scheduler_loop(paths: RuntimePaths, reproctl: str, workspace: str) -> int:
    paths.ensure()
    _set_scheduler(paths, state="running", pid=os.getpid(), started_at=utc_now(), last_error=None)
    paths.scheduler_pid.write_text(str(os.getpid()), encoding="utf-8")
    emit_event(paths, "scheduler.ready", data={"pid": os.getpid()})
    stop = False

    def on_term(_sig, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    idle_since: float | None = None
    try:
        while not stop:
            policy = load_gpu_policy(paths)
            sched_cfg = policy.get("scheduler") or {}
            poll = max(0.5, float(sched_cfg.get("poll_interval_seconds", 2.0)))
            idle_exit = max(5.0, float(sched_cfg.get("idle_exit_seconds", 30)))
            tasks = read_tasks(paths)

            # Recover stale "starting/running" tasks only when their worker is gone.
            for task in tasks:
                if task.get("state") in ACTIVE_STATES:
                    worker_pid = task.get("worker_pid")
                    if worker_pid and pid_alive(int(worker_pid)):
                        continue
                    launcher_pid = task.get("launcher_pid")
                    if launcher_pid and pid_alive(int(launcher_pid)):
                        continue
                    # The worker vanished without finalization; fail closed so GPU can be released.
                    update_task(paths, str(task["task_id"]), state="failed", finished_at=utc_now(), error="task worker disappeared")
                    emit_event(paths, "task.failed", task_id=str(task["task_id"]), data={"error": "task worker disappeared"})
            tasks = read_tasks(paths)
            active = [t for t in tasks if t.get("state") in ACTIVE_STATES]
            queued = [t for t in tasks if t.get("state") in QUEUE_STATES]
            max_parallel = max(1, int(sched_cfg.get("max_parallel_tasks", max(1, len(policy.get("allowed_gpu_ids") or [])))))
            capacity = max(0, max_parallel - len(active))
            started_any = False

            # GPU-required tasks wait until the run-level GPU pool has been confirmed.
            if queued and any(int((t.get("gpu_request") or {}).get("count", 1) or 0) > 0 for t in queued) and not policy.get("configured"):
                for task in queued:
                    if int((task.get("gpu_request") or {}).get("count", 1) or 0) > 0 and task.get("state") != "waiting-resources":
                        update_task(paths, str(task["task_id"]), state="waiting-resources", progress={"message": "等待用户确认本次运行可调度 GPU"})
                _set_scheduler(paths, state="waiting-gpu-confirmation", pid=os.getpid())
                time.sleep(poll)
                continue

            _set_scheduler(paths, state="running", pid=os.getpid())
            queued = sorted(queued, key=lambda t: (-int(t.get("priority", 0)), str(t.get("created_at", ""))))
            for task in queued:
                if capacity <= 0:
                    break
                task_id = str(task["task_id"])
                ready, failed_dep = _dependencies_ready(task, tasks)
                if failed_dep:
                    update_task(paths, task_id, state="blocked", finished_at=utc_now(), error="dependency failed", gpu_ids=[])
                    emit_event(paths, "task.blocked", task_id=task_id, data={"reason": "dependency failed"})
                    continue
                if not ready:
                    if task.get("state") != "waiting-dependencies":
                        update_task(paths, task_id, state="waiting-dependencies", progress={"message": "等待前置任务完成"})
                    continue
                gpu_ids = _candidate_gpus(paths, task, tasks)
                if gpu_ids is None:
                    if task.get("state") != "waiting-resources":
                        update_task(paths, task_id, state="waiting-resources", progress={"message": "等待 GPU 资源"})
                    continue
                # Reserve GPU IDs before launching to prevent double scheduling.
                log_path = paths.logs / f"{task_id}.log"
                worker_log = paths.runtime / f"worker-{task_id}.log"
                update_task(paths, task_id, state="starting", gpu_ids=gpu_ids, log_path=str(log_path.relative_to(paths.run_root)), progress={"message": "已分配资源，正在启动"})
                emit_event(paths, "gpu.assigned", task_id=task_id, data={"gpu_ids": gpu_ids})
                handle = open(worker_log, "a", encoding="utf-8")
                argv = [sys.executable, reproctl, "--workspace", workspace, "scheduler", "task-worker", task_id]
                worker = subprocess.Popen(argv, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
                update_task(paths, task_id, worker_pid=worker.pid)
                emit_event(paths, "task.worker_started", task_id=task_id, data={"worker_pid": worker.pid})
                started_any = True
                capacity -= 1
                tasks = read_tasks(paths)

            tasks = read_tasks(paths)
            active_or_queue = [t for t in tasks if t.get("state") not in TERMINAL_STATES]
            if not active_or_queue:
                if idle_since is None:
                    idle_since = time.time()
                    emit_event(paths, "queue.drained", data={"task_count": len(tasks)})
                    _mark_execution_complete(paths, tasks)
                elif time.time() - idle_since >= idle_exit:
                    break
            else:
                idle_since = None
            if not started_any:
                time.sleep(poll)
    except Exception as exc:  # noqa: BLE001
        _set_scheduler(paths, state="failed", pid=os.getpid(), last_error=repr(exc))
        emit_event(paths, "scheduler.failed", data={"error": repr(exc)})
        raise
    finally:
        paths.scheduler_pid.unlink(missing_ok=True)
        current = scheduler_state(paths)
        if current.get("state") not in {"failed"}:
            _set_scheduler(paths, state="stopped", pid=None, stopped_at=utc_now())
        refresh_snapshot(paths)
    return 0


def _mark_execution_complete(paths: RuntimePaths, tasks: list[dict[str, Any]]) -> None:
    state = _read_json(paths.state, {}) or {}
    if not state:
        return
    failed = [t for t in tasks if t.get("state") not in {"succeeded", "skipped"}]
    pipeline = dict(state.get("pipeline") or {})
    steps = list(pipeline.get("steps") or [])
    for step in steps:
        if int(step.get("index", 0)) == 6:
            step["status"] = "failed" if failed else "completed"
    # Recalculate the minimal pipeline fields without importing reproctl.
    completed = sum(1 for s in steps if s.get("status") == "completed")
    total = max(1, len(steps))
    pipeline.update({
        "steps": steps,
        "completed_steps": completed,
        "remaining_steps": max(0, total - completed),
        "current_step": 6 if failed else min(7, total),
        "total_steps": total,
    })
    state.update({
        "pipeline": pipeline,
        "status": "failed" if failed else "execution-complete",
        "stage": "execution" if failed else "verification",
        "message": f"执行队列完成：{len(tasks)-len(failed)}/{len(tasks)} 成功" if failed else f"执行队列已全部完成（{len(tasks)} 个任务），等待结果核验",
        "updated_at": utc_now(),
        "eta_seconds": 0,
    })
    _atomic_json(paths.state, state)


def _parse_duration(text: str | None) -> int | None:
    if not text:
        return None
    text = text.strip()
    parts = text.split(":")
    try:
        nums = [int(float(x)) for x in parts]
    except ValueError:
        return None
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 1:
        return nums[0]
    return None


def _estimated_finish(eta: int | None) -> str | None:
    if eta is None:
        return None
    return datetime.fromtimestamp(time.time() + max(0, eta), tz=timezone.utc).isoformat()


def _progress_from_line(line: str, adapter: dict[str, Any], started: float) -> dict[str, Any] | None:
    kind = str(adapter.get("type", "auto"))
    native = NATIVE_PROGRESS_RE.search(line) if kind in {"auto", "native"} else None
    if native:
        current = float(native.group("current")); total = float(native.group("total"))
        fraction = current / total if total > 0 else 0.0
        elapsed = max(0.001, time.time() - started)
        speed = current / elapsed if current > 0 else None
        eta = int((total - current) / speed) if speed and total >= current else None
        return {
            "current": current, "total": total, "unit": str(adapter.get("unit", "item")),
            "percent": round(max(0.0, min(100.0, fraction * 100)), 3), "speed": speed,
            "speed_unit": f"{adapter.get('unit','item')}/s", "eta_seconds": eta,
            "eta_confidence": "high" if current >= max(3, total * 0.03) else "medium",
            "eta_source": "rolling-throughput", "estimated_finish_at": _estimated_finish(eta),
            "source": "native-REPRO_PROGRESS", "message": native.group("message").strip(),
        }
    if kind in {"auto", "tqdm"}:
        match = TQDM_RE.search(line)
        if match:
            current = float(match.group("current")); total = float(match.group("total"))
            eta = _parse_duration(match.group("eta"))
            elapsed = max(0.001, time.time() - started)
            speed = current / elapsed if current > 0 else None
            return {
                "current": current, "total": total, "unit": str(adapter.get("unit", "item")),
                "percent": float(match.group("percent")), "speed": speed,
                "speed_unit": f"{adapter.get('unit','item')}/s", "eta_seconds": eta,
                "eta_confidence": "high" if eta is not None else "medium",
                "eta_source": "tqdm" if eta is not None else "rolling-throughput",
                "estimated_finish_at": _estimated_finish(eta), "source": "tqdm",
                "message": str(adapter.get("message", "tqdm progress")),
            }
    if kind == "regex-log" and adapter.get("pattern"):
        try:
            match = re.search(str(adapter["pattern"]), line)
        except re.error:
            match = None
        if match and "current" in match.groupdict() and "total" in match.groupdict():
            current = float(match.group("current")); total = float(match.group("total"))
            fraction = current / total if total > 0 else 0.0
            elapsed = max(0.001, time.time() - started)
            speed = current / elapsed if current > 0 else None
            eta = int((total - current) / speed) if speed and total >= current else None
            return {
                "current": current, "total": total, "unit": str(adapter.get("unit", "item")),
                "percent": round(fraction * 100, 3), "speed": speed,
                "speed_unit": f"{adapter.get('unit','item')}/s", "eta_seconds": eta,
                "eta_confidence": "medium", "eta_source": "rolling-throughput",
                "estimated_finish_at": _estimated_finish(eta), "source": "regex-log",
                "message": str(adapter.get("message", "regex progress")),
            }
    return None


def _artifact_progress(adapter: dict[str, Any], workspace: Path, started: float) -> dict[str, Any] | None:
    kind = str(adapter.get("type", ""))
    if kind not in {"jsonl-line-count", "line-count", "file-count"}:
        return None
    raw_path = str(adapter.get("path", ""))
    if not raw_path:
        return None
    target = Path(raw_path)
    if not target.is_absolute():
        target = workspace / target
    total = adapter.get("total")
    try:
        total_f = float(total)
    except (TypeError, ValueError):
        return None
    if total_f <= 0:
        return None
    current = 0
    if kind in {"jsonl-line-count", "line-count"}:
        if target.exists():
            try:
                with target.open("rb") as handle:
                    current = sum(1 for _ in handle)
            except OSError:
                return None
    elif kind == "file-count":
        if target.exists() and target.is_dir():
            current = sum(1 for item in target.rglob(str(adapter.get("glob", "*"))) if item.is_file())
    elapsed = max(0.001, time.time() - started)
    speed = current / elapsed if current > 0 else None
    eta = int((total_f - current) / speed) if speed and total_f >= current else None
    return {
        "current": current, "total": total_f, "unit": str(adapter.get("unit", "item")),
        "percent": round(max(0.0, min(100.0, current / total_f * 100)), 3), "speed": speed,
        "speed_unit": f"{adapter.get('unit','item')}/s", "eta_seconds": eta,
        "eta_confidence": "high" if current >= max(3, total_f * 0.03) else "medium",
        "eta_source": "rolling-throughput", "estimated_finish_at": _estimated_finish(eta),
        "source": kind, "message": str(adapter.get("message", f"{kind} progress")),
    }


def _command_argv(spec: dict[str, Any]) -> list[str]:
    command = str(spec["command"])
    env_info = spec.get("execution_env") or {}
    project_prefix = str(env_info.get("prefix") or "")
    control_prefix = str(os.environ.get("CONDA_PREFIX", ""))
    if project_prefix and Path(project_prefix).resolve() != Path(control_prefix).resolve():
        conda = os.environ.get("PAPER_REPRO_CONDA_EXE") or os.environ.get("CONDA_EXE") or shutil_which("conda")
        if not conda:
            raise RuntimeErrorEx("conda executable unavailable for task worker")
        return [str(conda), "run", "--no-capture-output", "-p", project_prefix, "bash", "-lc", command]
    return ["bash", "-lc", command]



def sandbox_backend_status() -> dict[str, Any]:
    bwrap = shutil_which("bwrap")
    return {
        "available": bool(bwrap),
        "backend": "bubblewrap" if bwrap else None,
        "path": bwrap,
    }


def _mkdir_args_for_target(target: Path, home: Path) -> list[str]:
    args: list[str] = []
    try:
        rel = target.resolve().relative_to(home.resolve())
    except Exception:
        return args
    cur = home.resolve()
    for part in rel.parts:
        cur = cur / part
        args.extend(["--dir", str(cur)])
    return args


def build_sandbox_argv(paths: RuntimePaths, spec: dict[str, Any], argv: list[str], env: dict[str, str], gpu_ids: list[int]) -> tuple[list[str], dict[str, Any]]:
    policy = dict(spec.get("sandbox") or {})
    mode = str(policy.get("mode", "auto"))
    if mode == "trusted-off":
        return argv, {"enabled": False, "mode": mode, "backend": None, "degraded": True}
    status = sandbox_backend_status()
    if not status["available"]:
        raise RuntimeErrorEx(
            "Execution sandbox is required but bubblewrap (bwrap) is unavailable. "
            "Install bwrap, or explicitly opt into trusted-only execution with: "
            "paper-repro security sandbox set --mode trusted-off --yes"
        )
    bwrap = str(status["path"])
    workspace = Path(spec["workspace"]).resolve()
    home = Path.home().resolve()
    # The unified paper-repro credential/config store must never live inside a writable
    # project/run mount. Otherwise hiding $HOME would not prevent project code from
    # reading credentials through the workspace bind. Fail closed rather than trying
    # to punch a read-only hole into a user-controlled tree.
    allowed_root_paths = [Path(str(item)).expanduser().resolve() for item in (policy.get("allowed_roots", []) or [])]
    writable_roots = [workspace, paths.run_root.resolve(), *allowed_root_paths]
    for env_name in ["PAPER_REPRO_CONFIG_HOME", "PAPER_REPRO_CONFIG_FILE", "PAPER_REPRO_SECRETS_FILE", "PAPER_REPRO_MCP_CONFIG"]:
        raw = os.environ.get(env_name, "").strip()
        if not raw:
            continue
        sensitive_path = Path(raw).expanduser().resolve()
        for writable_root in writable_roots:
            if sensitive_path == writable_root or str(sensitive_path).startswith(str(writable_root) + os.sep):
                raise RuntimeErrorEx(
                    f"Security boundary violation: {env_name} resolves inside a writable project/run directory: {sensitive_path}. "
                    "Move paper-repro global configuration outside the project workspace before sandboxed execution."
                )
    cmd: list[str] = [
        bwrap, "--die-with-parent", "--new-session", "--unshare-user", "--unshare-pid", "--unshare-uts", "--unshare-ipc",
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--dir", "/var", "--tmpfs", "/var/tmp",
        "--dir", "/tmp/paper-repro-home", "--dir", "/tmp/paper-repro-config",
    ]
    if str(policy.get("network", "on")) != "on":
        cmd.append("--unshare-net")

    # Build a minimal filesystem from the empty bubblewrap mount namespace. Do not
    # expose the host root (even read-only): paper repositories are untrusted code,
    # and a root-owned research account could otherwise read /etc/shadow, sibling
    # projects or credentials on unrelated mounts. Bubblewrap resolves bind sources
    # from the host old-root, so exact project/Conda paths can be mounted safely.
    def ro_bind(host_path: str) -> None:
        hp = Path(host_path)
        if hp.exists():
            cmd.extend(["--ro-bind", str(hp), str(hp)])

    # Runtime/toolchain paths. Preserve the common merged-/usr compatibility symlinks.
    ro_bind("/usr")
    ro_bind("/sys")
    for compat in ["/bin", "/sbin", "/lib", "/lib64"]:
        cp = Path(compat)
        if cp.is_symlink():
            cmd.extend(["--symlink", os.readlink(cp), compat])
        elif cp.exists():
            cmd.extend(["--ro-bind", compat, compat])

    # Only non-secret OS configuration required by networking, TLS, NSS and locale.
    for etc_path in [
        "/etc/ld.so.cache", "/etc/ld.so.conf", "/etc/ld.so.conf.d",
        "/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf",
        "/etc/passwd", "/etc/group", "/etc/localtime", "/etc/timezone",
        "/etc/ssl/certs", "/etc/ca-certificates", "/etc/pki/ca-trust/extracted",
    ]:
        ro_bind(etc_path)

    run_root = paths.run_root.resolve()
    env_info = spec.get("execution_env") or {}
    project_prefix_raw = str(env_info.get("prefix") or "").strip()
    project_prefix = Path(project_prefix_raw).resolve() if project_prefix_raw else None
    control_prefix_raw = str(os.environ.get("CONDA_PREFIX", "")).strip()
    control_prefix = Path(control_prefix_raw).resolve() if control_prefix_raw else None
    if project_prefix and control_prefix and project_prefix == control_prefix:
        raise RuntimeErrorEx(
            "Security boundary violation: project Conda equals the paper-repro control Conda. "
            "Use a separate per-project Conda environment before sandboxed execution."
        )

    # `conda run` may live in a base installation separate from the control env. Expose
    # that base read-only, hide sibling envs, then re-expose only the control env (RO)
    # and this project's env (RW). This preserves compatibility without leaking other
    # project environments through the sandbox.
    conda_exe_raw = os.environ.get("PAPER_REPRO_CONDA_EXE") or os.environ.get("CONDA_EXE") or ""
    conda_exe = Path(conda_exe_raw).expanduser().resolve() if conda_exe_raw else None
    if conda_exe and conda_exe.exists():
        conda_root = conda_exe.parent.parent
        if conda_root == home:
            raise RuntimeErrorEx(
                "Security boundary violation: Conda base resolves to the entire HOME directory. "
                "Move Conda to a dedicated subdirectory or use trusted-off only for reviewed code."
            )
        cmd.extend(["--ro-bind", str(conda_root), str(conda_root)])
        envs_dir = conda_root / "envs"
        if envs_dir.exists():
            cmd.extend(["--tmpfs", str(envs_dir)])
    if control_prefix and control_prefix.exists():
        cmd.extend(["--ro-bind", str(control_prefix), str(control_prefix)])
    if project_prefix and project_prefix.exists():
        cmd.extend(["--bind", str(project_prefix), str(project_prefix)])

    # The current repository is writable because reproduction may patch/build code, but
    # paper-repro's control state inside `.paper-repro` is never writable/visible to
    # the project process. Overlay it with tmpfs, then re-expose only the cache and a
    # task-specific exchange directory at REPRO_RUN_DIR. This prevents untrusted code
    # from forging sandbox policy, secret allowlists, decisions, task registry or
    # Remote Contract state.
    cmd.extend(["--bind", str(workspace), str(workspace)])
    state_home = run_root.parent.parent if run_root.parent.name == "runs" else None
    task_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(spec.get("task_id") or "task"))[:120] or "task"
    if state_home and (state_home == workspace or str(state_home).startswith(str(workspace) + os.sep)):
        cache_root = state_home / "cache"
        cache_root.mkdir(parents=True, exist_ok=True)
        exchange_root = run_root / "execution" / "sandbox" / task_id
        exchange_root.mkdir(parents=True, exist_ok=True)
        try:
            cache_root.chmod(0o700)
            exchange_root.chmod(0o700)
        except OSError:
            pass
        cmd.extend(["--tmpfs", str(state_home)])
        cmd.extend(["--bind", str(cache_root), str(cache_root)])
        # Keep the externally visible REPRO_RUN_DIR path stable while exposing only
        # this task's exchange directory, not the real run metadata tree.
        cmd.extend(["--bind", str(exchange_root), str(run_root)])
    elif run_root != workspace and not str(run_root).startswith(str(workspace) + os.sep):
        # Non-standard state roots outside the workspace are also reduced to a task
        # exchange mount rather than exposing the full controller run directory.
        exchange_root = run_root / "execution" / "sandbox" / task_id
        exchange_root.mkdir(parents=True, exist_ok=True)
        cmd.extend(["--bind", str(exchange_root), str(run_root)])

    # Make repository-local OpenCode control files read-only even though the rest of
    # the repository is writable for controlled reproduction patches/builds.
    for protected in [workspace / ".git", workspace / ".opencode", workspace / "opencode.jsonc", workspace / "AGENTS.md"]:
        if protected.exists():
            cmd.extend(["--ro-bind", str(protected), str(protected)])

    # Optional external model/data roots are explicit user grants. Never infer other
    # mount points from the host. They are writable because the same grant controls
    # external download destinations and experiment artifacts.
    for external in allowed_root_paths:
        if external in {Path("/"), home} or not external.exists():
            raise RuntimeErrorEx(f"Unsafe/nonexistent sandbox allowed root: {external}")
        if external == workspace or str(external).startswith(str(workspace) + os.sep):
            continue
        cmd.extend(["--bind", str(external), str(external)])

    # NVIDIA user-space libraries come from /usr. Expose only host driver metadata
    # needed by common CUDA/NVML paths, not the host process table.
    if Path("/proc/driver/nvidia").exists():
        cmd.extend(["--ro-bind", "/proc/driver/nvidia", "/proc/driver/nvidia"])
    # Bubblewrap's synthetic /dev exposes only basic devices. Add the selected NVIDIA device nodes and driver control nodes.
    for dev in ["/dev/nvidiactl", "/dev/nvidia-uvm", "/dev/nvidia-uvm-tools", "/dev/nvidia-modeset"] + [f"/dev/nvidia{i}" for i in gpu_ids]:
        if Path(dev).exists():
            cmd += ["--dev-bind", dev, dev]
    if str(policy.get("network", "on")) == "on" and Path("/dev/infiniband").exists():
        cmd += ["--dev-bind", "/dev/infiniband", "/dev/infiniband"]
    cmd += ["--setenv", "HOME", "/tmp/paper-repro-home", "--setenv", "XDG_CONFIG_HOME", "/tmp/paper-repro-config"]
    cmd += ["--chdir", str(workspace), "--"] + argv
    return cmd, {"enabled": True, "mode": mode, "backend": "bubblewrap", "degraded": False}


def task_worker(paths: RuntimePaths, task_id: str) -> int:
    paths.ensure()
    task = task_by_id(paths, task_id)
    spec = read_specs(paths).get(task_id)
    if not task or not spec:
        raise RuntimeErrorEx(f"Missing task/spec: {task_id}")
    gpu_ids = [int(x) for x in task.get("gpu_ids") or []]
    workspace = Path(spec["workspace"]).resolve()
    log_rel = task.get("log_path") or f"execution/logs/{task_id}.log"
    log_path = paths.run_root / log_rel
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    started_at = utc_now()
    requested_secret_env = [str(x) for x in (spec.get("secret_env") or [])]
    env = sec.scrub_environment(os.environ.copy(), allow_names=requested_secret_env)
    # Explicitly re-inject only the task-scoped secrets previously authorized by the workspace policy.
    for name in requested_secret_env:
        if name in os.environ:
            env[name] = os.environ[name]
    env.update({
        "REPRO_RUN_DIR": str(paths.run_root),
        "REPRO_TASK_ID": task_id,
        "REPRO_GPU_IDS": ",".join(str(x) for x in gpu_ids),
        "REPRO_GPU_COUNT": str(len(gpu_ids)),
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "WANDB_MODE": env.get("WANDB_MODE", "offline"),
    })
    if gpu_ids:
        env["CUDA_VISIBLE_DEVICES"] = ",".join(str(x) for x in gpu_ids)
    argv = _command_argv(spec)
    argv, sandbox_state = build_sandbox_argv(paths, spec, argv, env, gpu_ids)
    update_task(paths, task_id, state="running", sandbox=sandbox_state, worker_pid=os.getpid(), started_at=started_at, progress={"message": "任务运行中"})
    emit_event(paths, "task.started", task_id=task_id, data={"gpu_ids": gpu_ids, "worker_pid": os.getpid(), "sandbox": sandbox_state})
    _append_jsonl(paths.commands, {
        "record_type": "task-start", "task_id": task_id, "stage": task.get("stage"),
        "command": task.get("command"), "cwd": str(workspace), "started_at": started_at,
        "gpu_ids": gpu_ids, "project_env": task.get("project_env"), "log": str(log_path.relative_to(paths.run_root)),
    })
    proc = subprocess.Popen(
        argv, cwd=workspace, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        bufsize=0, start_new_session=True,
    )
    update_task(paths, task_id, launcher_pid=proc.pid)
    timeout = int(spec.get("timeout_seconds", 86400) or 86400)
    adapter = dict(spec.get("progress_adapter") or {"type": "auto"})
    last_progress_write = 0.0
    last_event_percent = -1.0
    last_event_time = 0.0
    timed_out = False
    partial = ""
    try:
        with log_path.open("a", encoding="utf-8") as log:
            log.write(
                f"# paper-repro runtime task\n# task_id={task_id}\n# started_at={started_at}\n"
                f"# gpu_ids={gpu_ids}\n# project_conda={task.get('project_env')}\n# command={task.get('command')}\n\n"
            )
            log.flush()
            assert proc.stdout is not None
            fd = proc.stdout.fileno()
            while True:
                elapsed = time.time() - started
                if elapsed > timeout:
                    timed_out = True
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except OSError:
                        pass
                    break
                readable, _, _ = select.select([fd], [], [], 0.5)
                if readable:
                    chunk = os.read(fd, 8192)
                    if chunk:
                        text = chunk.decode("utf-8", errors="replace")
                        log.write(text); log.flush()
                        partial += text
                        pieces = re.split(r"[\r\n]+", partial)
                        partial = pieces.pop() if pieces else ""
                        for line in pieces:
                            progress = _progress_from_line(line, adapter, started)
                            if progress:
                                now_t = time.time()
                                if now_t - last_progress_write >= 0.5:
                                    update_task(paths, task_id, progress=progress)
                                    last_progress_write = now_t
                                percent = float(progress.get("percent") or 0)
                                if percent >= last_event_percent + 1.0 or now_t - last_event_time >= 10:
                                    emit_event(paths, "task.progress", task_id=task_id, data={
                                        "current": progress.get("current"), "total": progress.get("total"),
                                        "percent": progress.get("percent"), "eta_seconds": progress.get("eta_seconds"),
                                        "source": progress.get("source"),
                                    })
                                    last_event_percent = percent; last_event_time = now_t
                artifact = _artifact_progress(adapter, workspace, started)
                if artifact and time.time() - last_progress_write >= 1.0:
                    update_task(paths, task_id, progress=artifact)
                    last_progress_write = time.time()
                if proc.poll() is not None:
                    # Drain remaining bytes.
                    try:
                        while True:
                            chunk = os.read(fd, 8192)
                            if not chunk:
                                break
                            text = chunk.decode("utf-8", errors="replace")
                            log.write(text)
                    except OSError:
                        pass
                    break
            if timed_out:
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except OSError:
                        pass
            code = proc.wait(timeout=20)
    except Exception as exc:  # noqa: BLE001
        try:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass
        update_task(paths, task_id, state="failed", finished_at=utc_now(), exit_code=1, error=repr(exc), progress={"eta_seconds": None, "message": "任务执行器异常"})
        emit_event(paths, "task.failed", task_id=task_id, data={"error": repr(exc)})
        raise

    elapsed = int(time.time() - started)
    state = "timeout" if timed_out else ("succeeded" if code == 0 else "failed")
    final_progress: dict[str, Any] = {"eta_seconds": 0 if state == "succeeded" else None, "estimated_finish_at": utc_now() if state == "succeeded" else None, "message": "任务完成" if state == "succeeded" else ("任务超时" if timed_out else "任务失败")}
    if state == "succeeded":
        current_task = task_by_id(paths, task_id) or {}
        current_progress = current_task.get("progress") or {}
        if current_progress.get("total") is not None:
            final_progress.update({"current": current_progress.get("total"), "percent": 100.0})
    update_task(paths, task_id, state=state, finished_at=utc_now(), exit_code=code, error=None if code == 0 else f"exit code {code}", progress=final_progress)
    _append_jsonl(paths.commands, {
        "record_type": "task-finish", "task_id": task_id, "stage": task.get("stage"),
        "finished_at": utc_now(), "state": state, "exit_code": code, "elapsed_seconds": elapsed,
        "log": str(log_path.relative_to(paths.run_root)),
    })
    emit_event(paths, f"task.{ 'completed' if state == 'succeeded' else state }", task_id=task_id, data={"exit_code": code, "elapsed_seconds": elapsed})
    if gpu_ids:
        emit_event(paths, "gpu.released", task_id=task_id, data={"gpu_ids": gpu_ids})
    refresh_snapshot(paths)
    return 0 if state == "succeeded" else (code or 1)


def refresh_snapshot(paths: RuntimePaths) -> dict[str, Any]:
    paths.ensure()
    tasks = read_tasks(paths)
    gpu = gpu_snapshot(paths)
    scheduler = scheduler_state(paths)
    active = [t for t in tasks if t.get("state") in ACTIVE_STATES]
    queued = [t for t in tasks if t.get("state") in QUEUE_STATES]
    terminal = [t for t in tasks if t.get("state") in TERMINAL_STATES]
    summary = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": utc_now(),
        "run_id": paths.run_root.name,
        "scheduler": scheduler,
        "queue": {
            "total": len(tasks), "active": len(active), "queued": len(queued), "terminal": len(terminal),
            "succeeded": sum(1 for t in terminal if t.get("state") == "succeeded"),
            "failed": sum(1 for t in terminal if t.get("state") in {"failed", "timeout", "blocked", "cancelled"}),
        },
        "active_tasks": active,
        "tasks": tasks,
        "gpu": gpu,
    }
    _atomic_json(paths.snapshot, summary)
    return summary


def read_events_after(paths: RuntimePaths, after: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    if not paths.remote_events.exists():
        return []
    result: list[dict[str, Any]] = []
    passed = after in (None, "", "0")
    with paths.remote_events.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not passed:
                if item.get("event_id") == after:
                    passed = True
                continue
            if after and item.get("event_id") == after:
                continue
            result.append(item)
            if len(result) >= limit:
                break
    return result


def read_events_page(paths: RuntimePaths, after: str | None = None, limit: int = 500) -> dict[str, Any]:
    """Return a cursor-aware page of run-scoped semantic events.

    Event IDs are monotonic only inside one run. Remote clients must therefore persist
    the tuple (run_id, event_id) and reset the cursor when run_id changes.
    """
    limit = max(1, min(int(limit or 500), 5000))
    if not paths.remote_events.exists():
        return {
            "after": after or None, "cursor_found": after in (None, "", "0"),
            "events": [], "next_cursor": after or None, "has_more": False,
        }
    result: list[dict[str, Any]] = []
    passed = after in (None, "", "0")
    cursor_found = passed
    with paths.remote_events.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not passed:
                if item.get("event_id") == after:
                    passed = True
                    cursor_found = True
                continue
            if after and item.get("event_id") == after:
                continue
            result.append(item)
            if len(result) >= limit + 1:
                break
    has_more = len(result) > limit
    page = result[:limit]
    next_cursor = page[-1].get("event_id") if page else (after or None)
    return {
        "after": after or None,
        "cursor_found": cursor_found,
        "events": page,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


def cancel_task(paths: RuntimePaths, task_id: str) -> dict[str, Any]:
    task = task_by_id(paths, task_id)
    if not task:
        raise RuntimeErrorEx(f"Unknown task: {task_id}")
    if task.get("state") in TERMINAL_STATES:
        return task
    for pid_key in ("launcher_pid", "worker_pid"):
        pid = task.get(pid_key)
        if pid and pid_alive(int(pid)):
            try:
                os.killpg(int(pid), signal.SIGTERM)
            except OSError:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except OSError:
                    pass
    updated = update_task(paths, task_id, state="cancelled", finished_at=utc_now(), progress={"eta_seconds": None, "message": "任务已取消"})
    emit_event(paths, "task.cancelled", task_id=task_id)
    return updated


def retry_task(paths: RuntimePaths, task_id: str) -> dict[str, Any]:
    task = task_by_id(paths, task_id)
    if not task:
        raise RuntimeErrorEx(f"Unknown task: {task_id}")
    if task.get("state") not in TERMINAL_STATES:
        raise RuntimeErrorEx(f"Task {task_id} is not terminal")
    updated = update_task(paths, task_id,
        state="queued", gpu_ids=[], launcher_pid=None, worker_pid=None,
        started_at=None, finished_at=None, exit_code=None, error=None,
        progress={"current": 0, "percent": 0.0, "speed": None, "eta_seconds": None, "eta_confidence": "unknown", "eta_source": None, "source": "unknown", "message": "等待重试调度"},
    )
    emit_event(paths, "task.retried", task_id=task_id)
    return updated
