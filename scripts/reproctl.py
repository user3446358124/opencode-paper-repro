#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import base64
import csv
import getpass
import hashlib
import mimetypes
import json
import os
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
import urllib.parse
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import runtime_engine as rte
import security as sec

sec.secure_umask()

SYSTEM_HOME = Path(__file__).resolve().parent.parent
VERSION_FILE = SYSTEM_HOME / "VERSION"
SYSTEM_VERSION = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else "2.2.1"
GLOBAL_STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "opencode-paper-repro"
REGISTRY_FILE = GLOBAL_STATE / "registry.json"
GLOBAL_ISSUES = GLOBAL_STATE / "issues.jsonl"
GLOBAL_SYSTEM_EVENTS = GLOBAL_STATE / "system-events.jsonl"
SELF_IMPROVE_HOME = GLOBAL_STATE / "self-improve"
IMPROVE_QUEUE = SELF_IMPROVE_HOME / "queue.jsonl"
IMPROVE_SESSIONS = SELF_IMPROVE_HOME / "sessions"
IMPROVE_BACKUPS = SELF_IMPROVE_HOME / "backups"
IMPROVE_HISTORY = SELF_IMPROVE_HOME / "history.jsonl"
PUBLISH_HOME = GLOBAL_STATE / "publish"
PUBLISH_QUEUE = PUBLISH_HOME / "queue.jsonl"
PUBLISH_SESSIONS = PUBLISH_HOME / "sessions"
PUBLISH_HISTORY = PUBLISH_HOME / "history.jsonl"
PAPER_REPRO_CONFIG_HOME = Path(os.environ.get("PAPER_REPRO_CONFIG_HOME", Path.home() / ".config/paper-repro")).expanduser()
UNIFIED_CONFIG_FILE = Path(os.environ.get("PAPER_REPRO_CONFIG_FILE", PAPER_REPRO_CONFIG_HOME / "config.json")).expanduser()
# Legacy paths are read during migration only. v0.7+ stores user-editable global settings in UNIFIED_CONFIG_FILE.
MODEL_ROUTING_FILE = Path(os.environ.get("PAPER_REPRO_MODEL_ROUTING", PAPER_REPRO_CONFIG_HOME / "model-routing.json")).expanduser()
MCP_SETTINGS_FILE = Path(os.environ.get("PAPER_REPRO_MCP_SETTINGS", PAPER_REPRO_CONFIG_HOME / "mcp-settings.json")).expanduser()
LEGACY_SECRETS_FILE = Path(os.environ.get("PAPER_REPRO_SECRETS_FILE", PAPER_REPRO_CONFIG_HOME / "secrets.json")).expanduser()
MCP_RUNTIME_CONFIG = Path(os.environ.get("PAPER_REPRO_MCP_CONFIG", PAPER_REPRO_CONFIG_HOME / "opencode.mcp.runtime.json")).expanduser()
SECRETS_FILE = UNIFIED_CONFIG_FILE
SECRET_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")
KNOWN_SECRET_NAMES = [
    "PAPER_VISION_API_KEY",
    "CONTEXT7_API_KEY",
    "GITHUB_MCP_TOKEN",
    "GITHUB_TOKEN",
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "BRAVE_API_KEY",
    "BRAVE_API_KEY_FILE",
    "GITHUB_PUBLISH_TOKEN",
]

MCP_SERVER_ORDER = ["context7", "github-readonly", "huggingface", "brave-search"]

STANDARD_PIPELINE = [
    (1, "paper-audit", "论文实验与结果清单"),
    (2, "repo-audit", "代码功能与入口清单"),
    (3, "coverage", "论文—代码复现覆盖矩阵"),
    (4, "assets", "模型、数据集与权重解析/下载"),
    (5, "environment", "项目 Conda 环境构建与锁定"),
    (6, "execution", "分级实验执行"),
    (7, "verification", "结果对齐与偏差分析"),
    (8, "reporting", "报告、摘要与问题归档"),
]

BLOCKED = [
    re.compile(r"(^|\s)sudo(\s|$)", re.I),
    re.compile(r"(^|\s)(apt|apt-get|yum|dnf|pacman)(\s|$)", re.I),
    re.compile(r"rm\s+-rf\s+/(\s|$)", re.I),
    re.compile(r"(^|\s)mkfs(\.|\s)", re.I),
    re.compile(r"(^|\s)dd\s+if=", re.I),
    re.compile(r"git\s+push\s+.*--force", re.I),
    re.compile(r"(curl|wget)[^|;&]*\|\s*(bash|sh)(\s|$)", re.I),
]
PROGRESS = re.compile(r"REPRO_PROGRESS\s+(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)\s*(.*)")


@dataclass(frozen=True)
class WorkspacePaths:
    workspace: Path
    state_home: Path

    @property
    def runs(self) -> Path:
        return self.state_home / "runs"

    @property
    def current(self) -> Path:
        return self.state_home / "current"

    @property
    def current_txt(self) -> Path:
        return self.state_home / "current.txt"

    @property
    def system(self) -> Path:
        return self.state_home / "system"

    @property
    def cache(self) -> Path:
        return self.state_home / "cache"

    @property
    def enabled(self) -> Path:
        return self.state_home / "enabled.json"

    @property
    def config(self) -> Path:
        return self.state_home / "config.json"


@dataclass(frozen=True)
class RunPaths:
    root: Path

    @property
    def meta(self) -> Path:
        return self.root / "meta"

    @property
    def analysis(self) -> Path:
        return self.root / "analysis"

    @property
    def assets(self) -> Path:
        return self.root / "assets"

    @property
    def environment(self) -> Path:
        return self.root / "environment"

    @property
    def execution(self) -> Path:
        return self.root / "execution"

    @property
    def runtime(self) -> Path:
        return self.root / "runtime"

    @property
    def logs(self) -> Path:
        return self.execution / "logs"

    @property
    def results(self) -> Path:
        return self.root / "results"

    @property
    def report(self) -> Path:
        return self.root / "report"

    @property
    def state(self) -> Path:
        return self.meta / "state.json"

    @property
    def manifest(self) -> Path:
        return self.meta / "manifest.json"

    @property
    def events(self) -> Path:
        return self.meta / "events.jsonl"

    @property
    def issues(self) -> Path:
        """Compatibility alias for pre-0.5 run-local issue data."""
        return self.meta / "issues.jsonl"

    @property
    def blockers(self) -> Path:
        return self.meta / "blockers.jsonl"

    @property
    def decisions(self) -> Path:
        return self.meta / "decisions.jsonl"

    @property
    def decisions_markdown(self) -> Path:
        return self.report / "DECISIONS.md"

    @property
    def decision_checkpoint(self) -> Path:
        return self.meta / "decision-checkpoint.json"

    @property
    def code_guide(self) -> Path:
        return self.report / "code-guide"

    @property
    def commands(self) -> Path:
        return self.execution / "commands.jsonl"

    @property
    def gpu(self) -> Path:
        return self.execution / "gpu.csv"

    @property
    def opencode_binding(self) -> Path:
        return self.meta / "opencode-binding.json"

    @property
    def remote_commands(self) -> Path:
        return self.meta / "remote-commands.jsonl"

    @property
    def artifacts(self) -> Path:
        return self.assets / "artifacts.jsonl"


class ReproError(RuntimeError):
    pass


class DecisionPendingError(ReproError):
    """Expected pause while one or more semantic decisions await user confirmation."""
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def append_jsonl(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")
    os.chmod(path, 0o600)


def secure_atomic_json(path: Path, data: Any) -> None:
    """Atomically write sensitive JSON with user-only permissions."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def default_unified_config() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "updated_at": now(),
        "secrets": {},
        "model_routing": {},
        "mcp": {},
        "decision_policy": {},
        "decision_preferences": {},
        "self_improvement": {},
        "github_publish": {},
    }


def load_unified_config(*, migrate_legacy: bool = True) -> dict[str, Any]:
    data = read_json(UNIFIED_CONFIG_FILE, {}) or {}
    if not isinstance(data, dict):
        raise ReproError(f"Invalid unified config format: {UNIFIED_CONFIG_FILE}")
    result = default_unified_config()
    result.update({key: value for key, value in data.items() if key not in {"secrets", "model_routing", "mcp", "decision_policy", "decision_preferences", "self_improvement", "github_publish"}})
    for key in ["secrets", "model_routing", "mcp", "decision_policy", "decision_preferences", "self_improvement", "github_publish"]:
        value = data.get(key, {})
        result[key] = value if isinstance(value, dict) else {}
    migrated: list[str] = []
    if migrate_legacy:
        if not result["secrets"] and LEGACY_SECRETS_FILE.exists() and LEGACY_SECRETS_FILE != UNIFIED_CONFIG_FILE:
            legacy = read_json(LEGACY_SECRETS_FILE, {}) or {}
            values = legacy.get("secrets", {}) if isinstance(legacy, dict) else {}
            if isinstance(values, dict):
                result["secrets"].update({str(k): str(v) for k, v in values.items() if isinstance(v, str)})
                migrated.append(str(LEGACY_SECRETS_FILE))
        if not result["model_routing"] and MODEL_ROUTING_FILE.exists() and MODEL_ROUTING_FILE != UNIFIED_CONFIG_FILE:
            legacy = read_json(MODEL_ROUTING_FILE, {}) or {}
            if isinstance(legacy, dict):
                result["model_routing"] = legacy
                migrated.append(str(MODEL_ROUTING_FILE))
        if not result["mcp"] and MCP_SETTINGS_FILE.exists() and MCP_SETTINGS_FILE != UNIFIED_CONFIG_FILE:
            legacy = read_json(MCP_SETTINGS_FILE, {}) or {}
            if isinstance(legacy, dict):
                result["mcp"] = legacy
                migrated.append(str(MCP_SETTINGS_FILE))
        if migrated:
            result["migration"] = {"imported_at": now(), "legacy_files": migrated}
            save_unified_config(result)
    return result


def save_unified_config(data: dict[str, Any]) -> None:
    payload = default_unified_config()
    payload.update(data)
    payload["schema_version"] = 1
    payload["updated_at"] = now()
    for key in ["secrets", "model_routing", "mcp", "decision_policy", "decision_preferences", "self_improvement", "github_publish"]:
        if not isinstance(payload.get(key), dict):
            payload[key] = {}
    secure_atomic_json(UNIFIED_CONFIG_FILE, payload)


def default_secrets_store() -> dict[str, Any]:
    return {"schema_version": 1, "updated_at": now(), "secrets": {}}


def load_secrets_store() -> dict[str, Any]:
    config = load_unified_config()
    secrets = config.get("secrets", {})
    cleaned: dict[str, str] = {}
    for name, value in secrets.items():
        if SECRET_NAME_RE.fullmatch(str(name)) and isinstance(value, str):
            cleaned[str(name)] = value
    return {"schema_version": 1, "updated_at": config.get("updated_at", ""), "secrets": cleaned}


def save_secrets_store(data: dict[str, Any]) -> None:
    config = load_unified_config()
    config["secrets"] = dict(sorted((data.get("secrets") or {}).items()))
    save_unified_config(config)


def apply_persistent_secrets(*, overwrite: bool = False) -> list[str]:
    """Load persisted secrets into this process without overriding explicit shell variables."""
    try:
        store = load_secrets_store()
    except Exception:
        return []
    loaded: list[str] = []
    for name, value in store["secrets"].items():
        if overwrite or not os.environ.get(name):
            os.environ[name] = value
            loaded.append(name)
    return loaded


def secret_summary(name: str, value: str) -> dict[str, Any]:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12] if value else ""
    return {
        "name": name,
        "configured": bool(value),
        "length": len(value),
        "fingerprint": digest,
        "active_in_process": bool(os.environ.get(name)),
    }


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def redact(text: str) -> str:
    try:
        values = list(load_secrets_store().get("secrets", {}).values())
    except Exception:
        values = []
    return sec.redact_text(text, values)


def capture(cmd: list[str], cwd: Path | None = None, timeout: int = 20) -> str:
    try:
        return subprocess.check_output(
            cmd, text=True, stderr=subprocess.STDOUT, timeout=timeout, cwd=str(cwd) if cwd else None
        ).strip()
    except Exception as exc:
        return f"unavailable: {exc}"


def git_root(start: Path) -> Path | None:
    out = capture(["git", "rev-parse", "--show-toplevel"], cwd=start)
    if out.startswith("unavailable:"):
        return None
    candidate = Path(out.splitlines()[-1]).expanduser().resolve()
    return candidate if candidate.exists() else None


def iter_ancestors(start: Path) -> Iterable[Path]:
    current = start.resolve()
    yield current
    yield from current.parents


def load_registry() -> dict[str, Any]:
    return read_json(REGISTRY_FILE, {"version": 1, "workspaces": {}})


def save_registry(data: dict[str, Any]) -> None:
    GLOBAL_STATE.mkdir(parents=True, exist_ok=True)
    atomic_json(REGISTRY_FILE, data)


def register_workspace(paths: WorkspacePaths, run: Path) -> None:
    registry = load_registry()
    workspaces = registry.setdefault("workspaces", {})
    workspace_id = _workspace_id(paths)
    current_path = str(paths.workspace)
    stale_same_id: list[str] = []
    live_duplicate = False
    for other_path, info in list(workspaces.items()):
        if other_path == current_path or info.get("workspace_id") != workspace_id:
            continue
        other_state = Path(str(info.get("state_home") or "")).expanduser()
        if other_state.exists():
            live_duplicate = True
        else:
            stale_same_id.append(other_path)
    # Moving a workspace preserves identity; copying it into a second live location does not.
    if live_duplicate:
        workspace_id = "ws-" + uuid.uuid4().hex[:12]
        config = workspace_config(paths)
        config["workspace_id"] = workspace_id
        save_workspace_config(paths, config)
    for old_path in stale_same_id:
        workspaces.pop(old_path, None)
    workspaces[current_path] = {
        "workspace_id": workspace_id,
        "state_home": str(paths.state_home),
        "last_run": str(run),
        "updated_at": now(),
    }
    save_registry(registry)


def latest_registered_workspace() -> Path | None:
    workspaces = load_registry().get("workspaces", {})
    entries = []
    for workspace, info in workspaces.items():
        if Path(info.get("state_home", "")).exists():
            entries.append((info.get("updated_at", ""), Path(workspace)))
    return max(entries)[1] if entries else None


def discover_workspace(explicit: str | None, state_root: str | None, latest: bool = False) -> WorkspacePaths:
    if explicit:
        workspace = Path(explicit).expanduser().resolve()
    elif os.environ.get("REPRO_WORKSPACE"):
        workspace = Path(os.environ["REPRO_WORKSPACE"]).expanduser().resolve()
    else:
        cwd = Path.cwd().resolve()
        workspace = None
        for parent in iter_ancestors(cwd):
            if (parent / ".paper-repro" / "current").exists() or (parent / ".paper-repro" / "current.txt").exists():
                workspace = parent
                break
        if workspace is None:
            workspace = git_root(cwd)
        if workspace is None and latest:
            workspace = latest_registered_workspace()
        if workspace is None:
            workspace = cwd

    if not workspace.exists():
        raise ReproError(f"Workspace does not exist: {workspace}")
    resolved_state = Path(state_root).expanduser().resolve() if state_root else workspace / ".paper-repro"
    return WorkspacePaths(workspace=workspace, state_home=resolved_state)


def resolve_run_marker(paths: WorkspacePaths) -> Path | None:
    if paths.current.is_symlink():
        target = paths.current.resolve()
        if target.exists():
            return target
    if paths.current.exists() and paths.current.is_dir():
        return paths.current.resolve()
    if paths.current_txt.exists():
        target = Path(paths.current_txt.read_text(encoding="utf-8").strip()).expanduser().resolve()
        if target.exists():
            return target
    return None


def current_run(paths: WorkspacePaths, allow_registry: bool = True) -> RunPaths:
    target = resolve_run_marker(paths)
    if target:
        return RunPaths(target)

    if allow_registry:
        info = load_registry().get("workspaces", {}).get(str(paths.workspace), {})
        candidate = Path(info.get("last_run", "")) if info.get("last_run") else None
        if candidate and candidate.exists():
            return RunPaths(candidate.resolve())

    legacy = paths.workspace / ".repro" / "current"
    hint = (
        f"No current run for workspace: {paths.workspace}\n"
        f"Searched: {paths.current}\n"
        "Create one with: paper-repro init --repository <URL> --paper <PDF>\n"
        f"Or select another workspace: paper-repro --workspace /path/to/project status --watch"
    )
    if legacy.exists() or legacy.is_symlink():
        hint += "\nLegacy state detected under .repro/. Run: paper-repro migrate-legacy"
    raise ReproError(hint)


def active_conda() -> tuple[str, str]:
    prefix = os.environ.get("CONDA_PREFIX", "")
    name = os.environ.get("CONDA_DEFAULT_ENV", "")
    if not prefix or name == "base":
        raise ReproError("A dedicated non-base Conda environment must be active")
    return prefix, name


def active_conda_info() -> dict[str, Any]:
    prefix = os.environ.get("CONDA_PREFIX", "")
    name = os.environ.get("CONDA_DEFAULT_ENV", "")
    python = str(Path(sys.executable).resolve())
    return {
        "name": name or "inactive",
        "prefix": prefix,
        "python": python,
        "is_active": bool(prefix),
        "is_base": name == "base",
        "role": "control",
    }


def conda_executable() -> str:
    for candidate in [
        os.environ.get("PAPER_REPRO_CONDA_EXE", ""),
        os.environ.get("CONDA_EXE", ""),
        shutil.which("conda") or "",
    ]:
        if candidate and Path(candidate).expanduser().exists():
            return str(Path(candidate).expanduser().resolve())
    raise ReproError("conda executable is not available; start with paper-opencode or activate the control Conda")


def conda_environments() -> list[dict[str, str]]:
    conda = conda_executable()
    raw = capture([conda, "env", "list", "--json"], timeout=30)
    if raw.startswith("unavailable:"):
        raise ReproError(raw)
    data = json.loads(raw)
    default_prefix = str(Path.home() / "miniconda3")
    rows: list[dict[str, str]] = []
    for item in data.get("envs", []):
        prefix = str(Path(item).expanduser().resolve())
        name = "base" if prefix == default_prefix else Path(prefix).name
        rows.append({"name": name, "prefix": prefix})
    return rows


def workspace_config(paths: WorkspacePaths) -> dict[str, Any]:
    data = read_json(paths.config, {}) or {}
    data.setdefault("schema_version", 1)
    data.setdefault("execution_env", None)
    data.setdefault("enforce_execution_env", True)
    paper = data.setdefault("paper_audit", {})
    paper.setdefault("vision_policy", "targeted")
    paper.setdefault("vision_verify_tables", True)
    paper.setdefault("vision_verify_method_figures", True)
    paper.setdefault("max_vision_pages", 24)
    paper.setdefault("dpi", 200)
    data.setdefault("decision_policy", {})
    data.setdefault("decision_preferences", {})
    security = data.setdefault("execution_security", {})
    sandbox = security.setdefault("sandbox", {})
    sandbox.setdefault("mode", "auto")
    sandbox.setdefault("backend", "auto")
    sandbox.setdefault("network", "on")
    security.setdefault("allowed_secret_env", [])
    security.setdefault("allowed_download_roots", [])
    security.setdefault("privacy_mode", "private")
    return data


def save_workspace_config(paths: WorkspacePaths, data: dict[str, Any]) -> None:
    ensure_workspace_layout(paths)
    data["updated_at"] = now()
    atomic_json(paths.config, data)


def execution_security_policy(paths: WorkspacePaths) -> dict[str, Any]:
    return dict(workspace_config(paths).get("execution_security") or {})


def _validate_task_secret_env(paths: WorkspacePaths, requested: Iterable[str]) -> list[str]:
    requested_names = [str(x).strip() for x in requested if str(x).strip()]
    allowed = {str(x) for x in execution_security_policy(paths).get("allowed_secret_env", [])}
    outside = [name for name in requested_names if name not in allowed]
    if outside:
        raise ReproError(
            "Task requested secret env not explicitly authorized for this workspace: " + ", ".join(outside) +
            ". Authorize with: paper-repro security secret allow NAME --yes"
        )
    return requested_names


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def allowed_download_roots(paths: WorkspacePaths) -> list[Path]:
    roots = [paths.workspace.resolve(), paths.cache.resolve()]
    for item in execution_security_policy(paths).get("allowed_download_roots", []):
        try:
            roots.append(Path(str(item)).expanduser().resolve())
        except Exception:
            pass
    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def task_sandbox_policy(paths: WorkspacePaths) -> dict[str, Any]:
    policy = dict(execution_security_policy(paths).get("sandbox") or {})
    # External roots are never inferred from the host filesystem. They become visible
    # to sandboxed project code only after the user explicitly authorizes them via
    # `security download-root add ... --yes`. The workspace/cache are already mounted.
    external: list[str] = []
    for root in allowed_download_roots(paths):
        if _path_within(root, paths.workspace):
            continue
        external.append(str(root.resolve()))
    policy["allowed_roots"] = sorted(set(external))
    return policy


def default_model_routing() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "policy": "native-first",
        "native": {
            "capability": "auto",
            "description": "Use the active OpenCode base model when it can directly inspect images.",
        },
        "profiles": {},
        "routes": {
            "vision": [],
            "document": [],
            "ocr": [],
            "table": [],
            "chart": [],
            "formula": [],
        },
    }


def model_routing_file(paths: WorkspacePaths | None = None, scope: str = "effective") -> Path:
    if scope == "workspace":
        if paths is None:
            raise ReproError("workspace scope requires a workspace")
        return paths.state_home / "model-routing.json"
    return MODEL_ROUTING_FILE


def merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_dict(result[key], value)
        else:
            result[key] = value
    return result


def model_routing(paths: WorkspacePaths | None = None) -> dict[str, Any]:
    data = default_model_routing()
    global_data = load_unified_config().get("model_routing", {}) or {}
    data = merge_dict(data, global_data)
    if paths is not None:
        local_file = model_routing_file(paths, "workspace")
        local_data = read_json(local_file, {}) or {}
        data = merge_dict(data, local_data)
    return data


def scoped_model_routing_data(paths: WorkspacePaths | None, scope: str) -> dict[str, Any]:
    if scope == "global":
        data = load_unified_config().get("model_routing", {}) or {}
        return dict(data) if isinstance(data, dict) else {}
    target = model_routing_file(paths, scope)
    data = read_json(target, {}) or {}
    return dict(data) if isinstance(data, dict) else {}


def save_model_routing(paths: WorkspacePaths | None, data: dict[str, Any], scope: str) -> Path:
    data["updated_at"] = now()
    if scope == "global":
        config = load_unified_config()
        config["model_routing"] = data
        save_unified_config(config)
        return UNIFIED_CONFIG_FILE
    target = model_routing_file(paths, scope)
    atomic_json(target, data)
    return target



DECISION_MODES = {
    "autonomous": {"ask_level": 3, "label": "高自动化"},
    "balanced": {"ask_level": 2, "label": "平衡模式"},
    "collaborative": {"ask_level": 1, "label": "协作模式"},
    "strict": {"ask_level": 1, "label": "谨慎模式"},
}

DECISION_HARD_CATEGORIES = {
    "license-access",
    "destructive",
    "system-level",
    "external-write",
    "credential-permission",
}


def default_decision_policy() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mode": "balanced",
        "max_interruptions_per_stage": 2,
        "max_interruptions_per_run": 8,
        "max_decisions_per_checkpoint": 3,
        "batch_related_decisions": True,
        "use_remembered_preferences": True,
        "auto_apply_safe_default_when_budget_exhausted": True,
        "thresholds": {
            "large_download_gb": 20,
            "long_task_hours": 4,
            "paid_api_cny": 20,
            "source_patch_files": 5,
        },
        "never_auto": sorted(DECISION_HARD_CATEGORIES),
    }


def decision_policy(paths: WorkspacePaths | None = None) -> dict[str, Any]:
    policy = merge_dict(default_decision_policy(), load_unified_config().get("decision_policy", {}) or {})
    if paths is not None:
        local = workspace_config(paths).get("decision_policy", {}) or {}
        policy = merge_dict(policy, local)
    mode = str(policy.get("mode", "balanced"))
    if mode not in DECISION_MODES:
        mode = "balanced"
        policy["mode"] = mode
    policy["ask_level"] = int(policy.get("ask_level", DECISION_MODES[mode]["ask_level"]))
    return policy


def save_decision_policy(paths: WorkspacePaths | None, data: dict[str, Any], scope: str) -> None:
    data["updated_at"] = now()
    if scope == "global":
        config = load_unified_config()
        config["decision_policy"] = data
        save_unified_config(config)
        return
    if paths is None:
        raise ReproError("workspace scope requires a workspace")
    config = workspace_config(paths)
    config["decision_policy"] = data
    save_workspace_config(paths, config)


def decision_preferences(paths: WorkspacePaths | None = None) -> dict[str, Any]:
    preferences = dict(load_unified_config().get("decision_preferences", {}) or {})
    if paths is not None:
        local = workspace_config(paths).get("decision_preferences", {}) or {}
        preferences.update(local)
    return preferences


def save_decision_preference(paths: WorkspacePaths, key: str, option_id: str, scope: str) -> None:
    entry = {"option_id": option_id, "updated_at": now()}
    if scope == "global":
        config = load_unified_config()
        prefs = config.setdefault("decision_preferences", {})
        prefs[key] = entry
        save_unified_config(config)
        return
    config = workspace_config(paths)
    prefs = config.setdefault("decision_preferences", {})
    prefs[key] = entry
    save_workspace_config(paths, config)


def decision_records(path: Path) -> list[dict[str, Any]]:
    return issue_records(path)


def folded_decisions(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    folded: dict[str, dict[str, Any]] = {}
    for record in records:
        decision_id = record.get("decision_id")
        if not decision_id:
            continue
        action = record.get("action", "opened")
        if action == "opened":
            folded[decision_id] = dict(record)
            folded[decision_id]["status"] = record.get("status", "pending")
        elif decision_id in folded:
            folded[decision_id].update({
                "status": record.get("status", "resolved"),
                "resolved_at": record.get("ts"),
                "selected_option": record.get("selected_option", ""),
                "resolution_note": record.get("resolution_note", ""),
                "remember_scope": record.get("remember_scope", "none"),
                "user_involved": bool(record.get("user_involved", False)),
            })
    return sorted(folded.values(), key=lambda item: item.get("ts", ""), reverse=True)


def pending_decisions(run: RunPaths, *, blocking_only: bool = False) -> list[dict[str, Any]]:
    items = [item for item in folded_decisions(decision_records(run.decisions)) if item.get("status") == "pending"]
    if blocking_only:
        items = [item for item in items if item.get("blocking", False)]
    return items


def render_decisions_markdown(run: RunPaths) -> None:
    items = folded_decisions(decision_records(run.decisions))
    pending = [item for item in items if item.get("status") == "pending"]
    lines = [
        "# 复现决策记录",
        "",
        f"- 系统版本：`{SYSTEM_VERSION}`",
        f"- 生成时间：`{now()}`",
        f"- 决策总数：`{len(items)}`",
        f"- 待用户确认：`{len(pending)}`",
        "",
        "> 低风险、可逆且有明显优选项的决策会自动执行并记录；会改变实验语义、产生显著成本或涉及不可逆/外部副作用的决策需要用户确认。",
        "",
    ]
    if not items:
        lines.append("当前尚无决策记录。")
    for item in items:
        lines.extend([
            f"## {item.get('title', '未命名决策')}",
            "",
            f"- ID：`{item.get('decision_id')}`",
            f"- 阶段：`{item.get('stage', '')}`",
            f"- 类别：`{item.get('category', '')}`",
            f"- 决策等级：`L{item.get('level', '?')}`",
            f"- 处理方式：`{item.get('handling', '')}`",
            f"- 状态：`{item.get('status', '')}`",
            f"- 问题：{item.get('question', '')}",
        ])
        if item.get("selected_option"):
            lines.append(f"- 已选择：`{item.get('selected_option')}`")
        options = item.get("options") or []
        if options:
            lines.append("- 选项：")
            for option in options:
                marker = "（推荐）" if option.get("recommended") else ""
                lines.append(f"  - `{option.get('id')}`：{option.get('label', '')}{marker}；{option.get('consequence', '')}")
        lines.append("")
    run.decisions_markdown.parent.mkdir(parents=True, exist_ok=True)
    run.decisions_markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _decision_score(args: argparse.Namespace, policy: dict[str, Any]) -> tuple[int, int, list[str]]:
    reasons: list[str] = []
    impact_weights = {"low": 0, "medium": 2, "high": 4, "critical": 6}
    reversibility_weights = {"reversible": 0, "partial": 2, "irreversible": 4}
    score = impact_weights.get(args.impact, 2) + reversibility_weights.get(args.reversibility, 2)
    if args.category in set(policy.get("never_auto", [])) or args.category in DECISION_HARD_CATEGORIES:
        reasons.append("该类别被配置为必须人工确认")
        return max(score, 8), 3, reasons
    if args.confidence < 0.6:
        score += 2
        reasons.append("模型置信度较低")
    elif args.confidence < 0.8:
        score += 1
        reasons.append("模型置信度一般")
    if args.changes_results:
        score += 3
        reasons.append("会改变复现结果或实验语义")
    if args.external_side_effect:
        score += 3
        reasons.append("会产生工作区外部副作用")
    thresholds = policy.get("thresholds", {}) or {}
    if args.estimated_hours >= float(thresholds.get("long_task_hours", 4)):
        score += 2
        reasons.append("预计运行时间较长")
    elif args.estimated_hours >= 1:
        score += 1
    if args.estimated_cost_cny >= float(thresholds.get("paid_api_cny", 20)):
        score += 2
        reasons.append("预计付费成本超过阈值")
    if args.download_gb >= float(thresholds.get("large_download_gb", 20)):
        score += 2
        reasons.append("下载规模超过阈值")
    if args.patch_files >= int(thresholds.get("source_patch_files", 5)):
        score += 2
        reasons.append("将修改较多源代码文件")
    level = 0 if score <= 1 else 1 if score <= 4 else 2 if score <= 9 else 3
    return score, level, reasons


def _parse_decision_options(raw: str) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReproError(f"Invalid --options-json: {exc}") from exc
    if not isinstance(data, list) or not (2 <= len(data) <= 5):
        raise ReproError("Decision options must be a JSON list containing 2 to 5 options")
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            raise ReproError("Each decision option must be an object")
        option_id = str(item.get("id", "")).strip()
        label = str(item.get("label", "")).strip()
        if not option_id or not label or option_id in seen:
            raise ReproError("Each option requires a unique id and a label")
        seen.add(option_id)
        options.append({
            "id": option_id,
            "label": label,
            "consequence": str(item.get("consequence", "")),
            "recommended": bool(item.get("recommended", False)),
        })
    return options


def _decision_interruptions(run: RunPaths, stage: str) -> tuple[int, int]:
    resolved = [item for item in folded_decisions(decision_records(run.decisions)) if item.get("status") == "resolved" and item.get("user_involved")]
    return len(resolved), sum(1 for item in resolved if item.get("stage") == stage)


def cmd_decisions_policy_show(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    print(json.dumps(decision_policy(paths), ensure_ascii=False, indent=2))
    return 0


def cmd_decisions_policy_set(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    current = decision_policy(paths if args.scope == "workspace" else None)
    if args.mode:
        current["mode"] = args.mode
        current["ask_level"] = DECISION_MODES[args.mode]["ask_level"]
    for field in ["max_interruptions_per_stage", "max_interruptions_per_run", "max_decisions_per_checkpoint"]:
        value = getattr(args, field, None)
        if value is not None:
            current[field] = max(0, value)
    if args.batch_related_decisions is not None:
        current["batch_related_decisions"] = args.batch_related_decisions
    if args.use_remembered_preferences is not None:
        current["use_remembered_preferences"] = args.use_remembered_preferences
    save_decision_policy(paths, current, args.scope)
    print(json.dumps({"scope": args.scope, "policy": current}, ensure_ascii=False, indent=2))
    return 0


def cmd_decisions_assess(args: argparse.Namespace) -> int:
    # Some tool runtimes historically serialized missing optional values as the literal
    # string "undefined". Treat those as absent rather than failing a semantic decision.
    for field in ["default_option", "recommended_option", "preference_key", "stage", "context"]:
        value = getattr(args, field, "")
        if str(value).strip().lower() in {"undefined", "null", "none"}:
            setattr(args, field, "")
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    policy = decision_policy(paths)
    options = _parse_decision_options(args.options_json)
    option_ids = {item["id"] for item in options}
    marked_recommended = next((str(item["id"]) for item in options if item.get("recommended")), "")
    if not args.recommended_option and marked_recommended:
        args.recommended_option = marked_recommended
    if not args.default_option and args.recommended_option:
        args.default_option = args.recommended_option
    if args.default_option and args.default_option not in option_ids:
        raise ReproError("--default-option must match one option id")
    if args.recommended_option and args.recommended_option not in option_ids:
        raise ReproError("--recommended-option must match one option id")
    score, level, reasons = _decision_score(args, policy)
    ask_level = int(policy.get("ask_level", 2))
    decision_id = "dec-" + uuid.uuid4().hex[:10]
    remembered = None
    if args.preference_key and policy.get("use_remembered_preferences", True) and level < 3:
        remembered = decision_preferences(paths).get(args.preference_key)
        if isinstance(remembered, dict) and remembered.get("option_id") not in option_ids:
            remembered = None

    run_count, stage_count = _decision_interruptions(run, args.stage)
    budget_exhausted = (
        run_count >= int(policy.get("max_interruptions_per_run", 8))
        or stage_count >= int(policy.get("max_interruptions_per_stage", 2))
    )
    selected_option = ""
    user_required = level >= ask_level
    handling = "自动记录" if level == 0 else "自动执行并通知"
    if level == 3:
        user_required = True
        handling = "强制人工确认"
    elif remembered:
        selected_option = str(remembered.get("option_id"))
        user_required = False
        handling = "应用已记住的偏好"
    elif user_required:
        handling = "合并到决策检查点" if policy.get("batch_related_decisions", True) else "立即询问"
        if budget_exhausted and args.default_option and args.reversibility == "reversible" and not args.changes_results and policy.get("auto_apply_safe_default_when_budget_exhausted", True):
            selected_option = args.default_option
            user_required = False
            handling = "决策预算已满，采用安全默认项并记录"
            reasons.append("本阶段或本次运行的交互预算已达到上限")
    elif args.default_option or args.recommended_option:
        selected_option = args.default_option or args.recommended_option

    if not user_required and not selected_option:
        marked = next((item.get("id") for item in options if item.get("recommended")), "")
        if marked:
            selected_option = str(marked)
        else:
            user_required = True
            handling = "没有安全默认项，需要用户确认"
            reasons.append("候选项之间没有可自动采用的明确默认方案")

    record = {
        "ts": now(),
        "action": "opened",
        "decision_id": decision_id,
        "title": args.title,
        "question": args.question,
        "category": args.category,
        "stage": args.stage,
        "impact": args.impact,
        "reversibility": args.reversibility,
        "confidence": args.confidence,
        "score": score,
        "level": level,
        "handling": handling,
        "requires_user": user_required,
        "blocking": user_required,
        "options": options,
        "default_option": args.default_option,
        "recommended_option": args.recommended_option,
        "preference_key": args.preference_key,
        "reasons": reasons,
        "status": "pending" if user_required else "resolved",
        "selected_option": selected_option,
        "context": args.context,
    }
    append_jsonl(run.decisions, record)
    if not user_required:
        append_jsonl(run.decisions, {
            "ts": now(), "action": "resolved", "decision_id": decision_id, "status": "resolved",
            "selected_option": selected_option, "resolution_note": handling, "remember_scope": "none", "user_involved": False,
        })
    else:
        state = read_json(run.state, {}) or {}
        update_state(run, status="awaiting-decision", message=f"等待用户确认：{args.title}", pending_decision_count=len(pending_decisions(run)))
        atomic_json(run.decision_checkpoint, {"generated_at": now(), "stage": args.stage, "pending": pending_decisions(run)})
    render_decisions_markdown(run)
    event(run, "decision.assessed", decision_id=decision_id, level=level, handling=handling, requires_user=user_required)
    if user_required:
        rte.emit_event(_runtime_paths(paths, run), "decision.created", data={
            "decision_id": decision_id, "level": level, "stage": args.stage,
            "title": args.title, "blocking": bool(record.get("blocking", False)),
        })
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


def cmd_decisions_list(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    items = folded_decisions(decision_records(run.decisions))
    if args.pending:
        items = [item for item in items if item.get("status") == "pending"]
    print(json.dumps(items, ensure_ascii=False, indent=2))
    return 0


def cmd_decisions_resolve(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    items = {item.get("decision_id"): item for item in folded_decisions(decision_records(run.decisions))}
    item = items.get(args.decision_id)
    if not item or item.get("status") != "pending":
        raise ReproError(f"Pending decision not found: {args.decision_id}")
    option_ids = {option.get("id") for option in item.get("options", [])}
    if args.option not in option_ids:
        raise ReproError(f"Unknown option {args.option}; choose one of: {', '.join(sorted(str(x) for x in option_ids))}")
    append_jsonl(run.decisions, {
        "ts": now(), "action": "resolved", "decision_id": args.decision_id, "status": "resolved",
        "selected_option": args.option, "resolution_note": args.note, "remember_scope": args.remember,
        "user_involved": True,
    })
    preference_key = item.get("preference_key")
    if args.remember != "none" and preference_key and int(item.get("level", 0)) < 3:
        save_decision_preference(paths, str(preference_key), args.option, args.remember)
    remaining = pending_decisions(run, blocking_only=True)
    state = read_json(run.state, {}) or {}
    update_state(
        run,
        status="awaiting-decision" if remaining else "running",
        message=(f"仍有 {len(remaining)} 项决策待确认" if remaining else "决策已确认，可以继续执行"),
        pending_decision_count=len(remaining),
    )
    atomic_json(run.decision_checkpoint, {"generated_at": now(), "stage": item.get("stage", ""), "pending": remaining})
    render_decisions_markdown(run)
    event(run, "decision.resolved", decision_id=args.decision_id, selected_option=args.option, remember=args.remember)
    rte.emit_event(_runtime_paths(paths, run), "decision.resolved", data={
        "decision_id": args.decision_id, "selected_option": args.option, "remember": args.remember, "source": "local-cli",
    })
    print(json.dumps({"decision_id": args.decision_id, "selected_option": args.option, "remaining_pending": len(remaining)}, ensure_ascii=False, indent=2))
    return 0


def cmd_decisions_checkpoint(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    items = pending_decisions(run)
    if args.stage:
        items = [item for item in items if item.get("stage") == args.stage]
    items = sorted(items, key=lambda item: (int(item.get("level", 0)), item.get("ts", "")), reverse=True)
    max_items = max(1, int(decision_policy(paths).get("max_decisions_per_checkpoint", 3)))
    selected = items[:max_items]
    payload = {
        "generated_at": now(),
        "mode": decision_policy(paths).get("mode"),
        "pending_count": len(items),
        "checkpoint_count": len(selected),
        "deferred_count": max(0, len(items) - len(selected)),
        "pending": selected,
        "instruction": "本次最多询问这些高优先级决策；每项给出推荐项、主要代价和可逆性。其余待决策项延后到下一检查点。",
    }
    atomic_json(run.decision_checkpoint, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def parse_capabilities(raw: str) -> list[str]:
    allowed = {"vision", "document", "ocr", "table", "chart", "formula", "video"}
    values = []
    for item in raw.split(","):
        value = item.strip().lower()
        if not value:
            continue
        if value not in allowed:
            raise ReproError(f"Unsupported capability: {value}; allowed: {', '.join(sorted(allowed))}")
        if value not in values:
            values.append(value)
    if "vision" not in values:
        values.insert(0, "vision")
    return values


def selected_profiles(routing: dict[str, Any], task: str, explicit: str = "") -> list[tuple[str, dict[str, Any]]]:
    profiles = routing.get("profiles", {}) or {}
    names: list[str] = []
    if explicit:
        names = [explicit]
    else:
        names.extend((routing.get("routes", {}) or {}).get(task, []) or [])
        if task != "vision":
            names.extend((routing.get("routes", {}) or {}).get("vision", []) or [])
    output: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        profile = profiles.get(name)
        if not profile or profile.get("enabled", True) is False:
            continue
        capabilities = profile.get("capabilities", ["vision"])
        if task not in capabilities and "vision" not in capabilities:
            continue
        output.append((name, profile))
    return output


def media_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def parse_page_spec(spec: str, page_count: int) -> list[int]:
    if not spec:
        return [1]
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            start, end = int(left), int(right)
            if end < start:
                start, end = end, start
            pages.update(range(start, end + 1))
        else:
            pages.add(int(part))
    result = sorted(page for page in pages if 1 <= page <= page_count)
    if not result:
        raise ReproError(f"No valid PDF pages in '{spec}' (document has {page_count} pages)")
    return result


def prepare_vision_inputs(paths: WorkspacePaths, inputs: list[str], pages: str, dpi: int) -> list[Path]:
    prepared: list[Path] = []
    cache = paths.cache / "vision"
    cache.mkdir(parents=True, exist_ok=True)
    for raw in inputs:
        source = Path(raw).expanduser()
        if not source.is_absolute():
            source = (paths.workspace / source).resolve()
        if not source.exists():
            raise ReproError(f"Vision input does not exist: {source}")
        if source.suffix.lower() == ".pdf":
            try:
                import fitz
            except ImportError as exc:
                raise ReproError("PyMuPDF is required to render PDF pages") from exc
            document = fitz.open(source)
            selected = parse_page_spec(pages, document.page_count)
            digest = hashlib.sha256(str(source).encode("utf-8") + str(source.stat().st_mtime_ns).encode("ascii")).hexdigest()[:16]
            out_dir = cache / digest
            out_dir.mkdir(parents=True, exist_ok=True)
            zoom = max(72, dpi) / 72.0
            matrix = fitz.Matrix(zoom, zoom)
            for page_number in selected:
                target = out_dir / f"page-{page_number:04d}-{dpi}dpi.png"
                if not target.exists():
                    pixmap = document.load_page(page_number - 1).get_pixmap(matrix=matrix, alpha=False)
                    pixmap.save(target)
                prepared.append(target)
            document.close()
        else:
            mime = mimetypes.guess_type(source.name)[0] or ""
            if not mime.startswith("image/"):
                raise ReproError(f"Unsupported vision input type: {source}")
            prepared.append(source)
    if not prepared:
        raise ReproError("At least one image or PDF input is required")
    return prepared


def call_openai_compatible(profile_name: str, profile: dict[str, Any], prompt: str, images: list[Path], timeout: int) -> dict[str, Any]:
    try:
        import requests
    except ImportError as exc:
        raise ReproError("requests is required for fallback vision calls") from exc
    protocol = profile.get("protocol", "openai-compatible")
    if protocol != "openai-compatible":
        raise ReproError(f"Profile {profile_name} uses unsupported protocol: {protocol}")
    base_url = str(profile.get("base_url", "")).strip().rstrip("/")
    model = str(profile.get("model", "")).strip()
    key_env = str(profile.get("api_key_env", "")).strip()
    if not base_url or not model or not key_env:
        raise ReproError(f"Profile {profile_name} must define base_url, model and api_key_env")
    api_key = os.environ.get(key_env, "")
    if not api_key:
        raise ReproError(f"Environment variable {key_env} is not set for profile {profile_name}")
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for image in images:
        content.append({"type": "image_url", "image_url": {"url": media_data_url(image)}})
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": float(profile.get("temperature", 0)),
        "max_tokens": int(profile.get("max_tokens", 8192)),
    }
    extra = profile.get("request_options") or {}
    if isinstance(extra, dict):
        payload.update(extra)
    endpoint = base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"
    response = requests.post(
        endpoint,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=(30, timeout),
    )
    response.raise_for_status()
    body = response.json()
    try:
        answer = body["choices"][0]["message"]["content"]
    except Exception as exc:
        raise ReproError(f"Unexpected response from profile {profile_name}: {str(body)[:500]}") from exc
    return {
        "profile": profile_name,
        "protocol": protocol,
        "model": model,
        "base_url": base_url,
        "content": answer,
        "usage": body.get("usage"),
        "response_id": body.get("id"),
    }


def cmd_models_show(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    routing = model_routing(paths)
    safe = json.loads(json.dumps(routing))
    for profile in (safe.get("profiles", {}) or {}).values():
        key_env = profile.get("api_key_env")
        profile["api_key_available"] = bool(key_env and os.environ.get(str(key_env)))
    print(json.dumps({
        "workspace": str(paths.workspace),
        "policy": routing.get("policy"),
        "native": routing.get("native"),
        "global_config": str(UNIFIED_CONFIG_FILE),
        "workspace_config": str(model_routing_file(paths, "workspace")),
        "effective": safe,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_models_native(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    scope = args.scope
    target_paths = paths if scope == "workspace" else None
    target = scoped_model_routing_data(target_paths, scope)
    target.setdefault("schema_version", 1)
    target.setdefault("policy", "native-first")
    target["native"] = {"capability": args.capability}
    saved = save_model_routing(target_paths, target, scope)
    print(json.dumps({"saved": str(saved), "native": target["native"]}, ensure_ascii=False, indent=2))
    return 0


def cmd_models_profile_set(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    scope = args.scope
    target_paths = paths if scope == "workspace" else None
    target = scoped_model_routing_data(target_paths, scope)
    target.setdefault("schema_version", 1)
    target.setdefault("policy", "native-first")
    profiles = target.setdefault("profiles", {})
    profiles[args.name] = {
        "protocol": args.protocol,
        "base_url": args.base_url.rstrip("/"),
        "model": args.model,
        "api_key_env": args.api_key_env,
        "capabilities": parse_capabilities(args.capabilities),
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "enabled": True,
    }
    saved = save_model_routing(target_paths, target, scope)
    print(json.dumps({"saved": str(saved), "profile": args.name, "config": profiles[args.name]}, ensure_ascii=False, indent=2))
    return 0


def cmd_models_profile_remove(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    scope = args.scope
    target_paths = paths if scope == "workspace" else None
    target = scoped_model_routing_data(target_paths, scope)
    removed = (target.get("profiles", {}) or {}).pop(args.name, None)
    for names in (target.get("routes", {}) or {}).values():
        while args.name in names:
            names.remove(args.name)
    saved = save_model_routing(target_paths, target, scope)
    print(json.dumps({"saved": str(saved), "removed": bool(removed), "profile": args.name}, ensure_ascii=False, indent=2))
    return 0


def cmd_models_route(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    scope = args.scope
    target_paths = paths if scope == "workspace" else None
    target = scoped_model_routing_data(target_paths, scope)
    target.setdefault("schema_version", 1)
    target.setdefault("policy", "native-first")
    routes = target.setdefault("routes", {})
    routes[args.task] = args.profile
    saved = save_model_routing(target_paths, target, scope)
    print(json.dumps({"saved": str(saved), "task": args.task, "profiles": args.profile}, ensure_ascii=False, indent=2))
    return 0


def cmd_vision_analyze(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    routing = model_routing(paths)
    native_capability = str((routing.get("native") or {}).get("capability", "auto"))
    if args.native_result:
        output = {
            "route": "native",
            "native_capability": native_capability,
            "task": args.task,
            "content": args.native_result,
            "created_at": now(),
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    profiles = selected_profiles(routing, args.task, args.profile)
    if not profiles:
        raise ReproError(
            f"No fallback vision profile is configured for task '{args.task}'. "
            "Configure one with paper-repro models profile set, then route it with paper-repro models route."
        )
    images = prepare_vision_inputs(paths, args.input, args.pages, args.dpi)
    run = None
    try:
        run = current_run(paths)
    except Exception:
        pass
    failures: list[dict[str, str]] = []
    started = time.time()
    for profile_name, profile in profiles:
        try:
            result = call_openai_compatible(profile_name, profile, args.prompt, images, args.timeout)
            result.update({
                "route": "fallback",
                "policy": routing.get("policy", "native-first"),
                "native_capability": native_capability,
                "task": args.task,
                "prompt": args.prompt,
                "inputs": [str(item) for item in images],
                "created_at": now(),
                "elapsed_seconds": round(time.time() - started, 3),
            })
            if run:
                out_dir = run.analysis / "vision"
            else:
                out_dir = paths.state_home / "vision"
            out_dir.mkdir(parents=True, exist_ok=True)
            output_path = Path(args.output).expanduser() if args.output else out_dir / f"{local_stamp()}-{args.task}.json"
            if not output_path.is_absolute():
                output_path = (paths.workspace / output_path).resolve()
            atomic_json(output_path, result)
            result["saved_to"] = str(output_path)
            if run:
                event(run, "vision.fallback.completed", profile=profile_name, task=args.task, output=str(output_path))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:
            failures.append({"profile": profile_name, "error": str(exc)})
    details = json.dumps(failures, ensure_ascii=False)
    if run:
        record_issue(paths, run, title="多模态备用模型调用失败", details=details, severity="error", component="vision-router", stage="paper-audit")
    raise ReproError(f"All fallback vision profiles failed: {details}")


def cmd_vision_test(args: argparse.Namespace) -> int:
    args.prompt = args.prompt or "请简洁描述图片中的主要内容，并指出其中可见的文字、表格、图或公式。"
    return cmd_vision_analyze(args)


def paper_audit_policy(paths: WorkspacePaths) -> dict[str, Any]:
    return dict(workspace_config(paths).get("paper_audit") or {})


def cmd_paper_policy_show(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    print(json.dumps(paper_audit_policy(paths), ensure_ascii=False, indent=2))
    return 0


def cmd_paper_policy_set(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    config = workspace_config(paths)
    policy = config.setdefault("paper_audit", {})
    if args.vision_policy:
        policy["vision_policy"] = args.vision_policy
    if args.verify_tables is not None:
        policy["vision_verify_tables"] = args.verify_tables
    if args.verify_method_figures is not None:
        policy["vision_verify_method_figures"] = args.verify_method_figures
    if args.max_vision_pages is not None:
        policy["max_vision_pages"] = args.max_vision_pages
    if args.dpi is not None:
        policy["dpi"] = args.dpi
    save_workspace_config(paths, config)
    print(json.dumps(policy, ensure_ascii=False, indent=2))
    return 0


def _method_figure_hint(text: str) -> bool:
    words = [
        "architecture", "framework", "pipeline", "overview", "method", "model architecture",
        "network architecture", "system overview", "workflow", "模块", "框架", "架构", "流程", "方法总览",
    ]
    lower = text.lower()
    return any(word in lower for word in words)


def cmd_paper_inspect(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    source = Path(args.input).expanduser()
    if not source.is_absolute():
        source = (paths.workspace / source).resolve()
    if not source.exists():
        raise ReproError(f"论文 PDF 不存在：{source}")
    if source.suffix.lower() != ".pdf":
        raise ReproError(f"论文检查只接受 PDF：{source}")
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise ReproError("需要 PyMuPDF 才能检查 PDF 文本层和页面图像") from exc
    policy = paper_audit_policy(paths)
    if args.vision_policy:
        policy["vision_policy"] = args.vision_policy
    document = fitz.open(source)
    pages: list[dict[str, Any]] = []
    table_pages: list[int] = []
    figure_pages: list[int] = []
    method_figure_pages: list[int] = []
    scanned_pages: list[int] = []
    for index, page in enumerate(document, start=1):
        text = page.get_text("text") or ""
        clean = re.sub(r"\s+", " ", text).strip()
        image_count = len(page.get_images(full=True))
        table_hits = re.findall(r"(?i)(?:table|表)\s*[A-Z]?\d+", clean)
        figure_hits = re.findall(r"(?i)(?:figure|fig\.?|图)\s*[A-Z]?\d+", clean)
        low_text = len(clean) < args.low_text_threshold
        scanned = low_text and image_count > 0
        method_hint = bool(figure_hits and _method_figure_hint(clean))
        if table_hits:
            table_pages.append(index)
        if figure_hits:
            figure_pages.append(index)
        if method_hint:
            method_figure_pages.append(index)
        if scanned:
            scanned_pages.append(index)
        pages.append({
            "page": index,
            "text_chars": len(clean),
            "image_count": image_count,
            "has_text_layer": len(clean) >= args.low_text_threshold,
            "likely_scanned": scanned,
            "table_captions": table_hits,
            "figure_captions": figure_hits,
            "method_figure_hint": method_hint,
            "text_preview": clean[:500],
        })
    vision_policy = policy.get("vision_policy", "targeted")
    recommended: list[int] = []
    reasons: dict[str, list[int]] = {}
    if vision_policy == "all-pages":
        recommended = list(range(1, document.page_count + 1))
        reasons["all-pages"] = recommended
    elif vision_policy == "targeted":
        if scanned_pages:
            recommended.extend(scanned_pages)
            reasons["扫描页或文本层不足"] = scanned_pages
        if policy.get("vision_verify_tables", True) and table_pages:
            recommended.extend(table_pages)
            reasons["目标表格版面与单元格关系复核"] = table_pages
        if policy.get("vision_verify_method_figures", True) and method_figure_pages:
            recommended.extend(method_figure_pages)
            reasons["核心方法/架构图复核"] = method_figure_pages
    elif vision_policy == "on-demand":
        recommended = scanned_pages[:]
        if scanned_pages:
            reasons["仅在文本层不可用时调用视觉"] = scanned_pages
    elif vision_policy == "off":
        recommended = []
    recommended = sorted(set(recommended))[: int(policy.get("max_vision_pages", 24))]
    result = {
        "schema_version": 1,
        "paper": str(source),
        "page_count": document.page_count,
        "vision_policy": vision_policy,
        "policy": policy,
        "summary": {
            "pages_with_text_layer": len([p for p in pages if p["has_text_layer"]]),
            "likely_scanned_pages": scanned_pages,
            "table_pages": sorted(set(table_pages)),
            "figure_pages": sorted(set(figure_pages)),
            "method_figure_pages": sorted(set(method_figure_pages)),
            "recommended_vision_pages": recommended,
            "vision_reasons": reasons,
        },
        "pages": pages,
        "provenance_rule": {
            "text_layer": "用于精确文字、可复制数值、引用和全文检索",
            "vision": "用于页面版面、表格行列关系、图、公式、扫描内容与交叉核验",
            "combination": "targeted 策略下，两者结果必须在 paper_manifest.json 中分别记录并交叉验证",
        },
    }
    try:
        run = current_run(paths)
        output = run.analysis / "pdf_inventory.json"
        event(run, "paper.pdf.inspected", paper=str(source), vision_policy=vision_policy, recommended_pages=recommended)
    except ReproError:
        output = paths.state_home / "pdf_inventory.json"
    atomic_json(output, result)
    result["saved_to"] = str(output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


CODE_EXCLUDES = {
    ".git", ".paper-repro", ".repro", ".idea", ".vscode", "node_modules", "__pycache__",
    "dist", "build", ".tox", ".mypy_cache", ".pytest_cache", "site-packages", "wandb",
    "checkpoints", "outputs", "results", "data", "datasets",
}


def _source_files(workspace: Path, max_files: int = 5000) -> list[Path]:
    allowed = {".py", ".sh", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".md", ".cpp", ".cc", ".c", ".h", ".hpp", ".cu", ".java", ".rs", ".go", ".js", ".ts"}
    files: list[Path] = []
    for root, dirs, names in os.walk(workspace):
        dirs[:] = [name for name in dirs if name not in CODE_EXCLUDES and not name.startswith(".conda")]
        for name in names:
            path = Path(root) / name
            if path.suffix.lower() not in allowed or path.is_symlink():
                continue
            try:
                if path.stat().st_size > 2 * 1024 * 1024:
                    continue
            except OSError:
                continue
            files.append(path)
            if len(files) >= max_files:
                return files
    return files


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


class _PythonIndexVisitor(ast.NodeVisitor):
    def __init__(self, module: str):
        self.module = module
        self.scope: list[str] = []
        self.functions: list[dict[str, Any]] = []
        self.classes: list[dict[str, Any]] = []
        self.imports: list[str] = []
        self.calls: list[dict[str, str]] = []
        self.entrypoint = False

    def visit_Import(self, node: ast.Import) -> Any:
        self.imports.extend(alias.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        prefix = "." * node.level + (node.module or "")
        self.imports.extend(f"{prefix}:{alias.name}" for alias in node.names)

    def visit_If(self, node: ast.If) -> Any:
        try:
            test = ast.unparse(node.test)
        except Exception:
            test = ""
        if "__name__" in test and "__main__" in test:
            self.entrypoint = True
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        qualified = ".".join([self.module, *self.scope, node.name])
        bases = []
        for base in node.bases:
            try:
                bases.append(ast.unparse(base))
            except Exception:
                pass
        self.classes.append({"name": node.name, "qualified": qualified, "line": node.lineno, "end_line": getattr(node, "end_lineno", node.lineno), "bases": bases, "doc": ast.get_docstring(node) or ""})
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Any:
        qualified = ".".join([self.module, *self.scope, node.name])
        arguments = [arg.arg for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]]
        decorators = []
        for dec in node.decorator_list:
            try:
                decorators.append(ast.unparse(dec))
            except Exception:
                pass
        self.functions.append({
            "name": node.name,
            "qualified": qualified,
            "line": node.lineno,
            "end_line": getattr(node, "end_lineno", node.lineno),
            "arguments": arguments,
            "decorators": decorators,
            "doc": ast.get_docstring(node) or "",
        })
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        return self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        return self._visit_function(node)

    def visit_Call(self, node: ast.Call) -> Any:
        caller = ".".join([self.module, *self.scope]) if self.scope else self.module
        callee = _call_name(node.func)
        if callee:
            self.calls.append({"caller": caller, "callee": callee, "line": str(getattr(node, "lineno", ""))})
        self.generic_visit(node)


def build_code_index(paths: WorkspacePaths) -> dict[str, Any]:
    source_files = _source_files(paths.workspace)
    language_counts: dict[str, int] = {}
    python_modules: list[dict[str, Any]] = []
    parse_errors: list[dict[str, str]] = []
    for path in source_files:
        suffix = path.suffix.lower() or "<none>"
        language_counts[suffix] = language_counts.get(suffix, 0) + 1
        if suffix != ".py":
            continue
        relative = path.relative_to(paths.workspace)
        module = ".".join(relative.with_suffix("").parts)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(text, filename=str(relative))
            visitor = _PythonIndexVisitor(module)
            visitor.visit(tree)
            indicators = []
            for marker in ["argparse", "click", "typer", "hydra", "fire", "torchrun", "Trainer", "DataLoader"]:
                if marker in text:
                    indicators.append(marker)
            python_modules.append({
                "path": str(relative),
                "module": module,
                "lines": text.count("\n") + 1,
                "imports": sorted(set(visitor.imports)),
                "functions": visitor.functions,
                "classes": visitor.classes,
                "calls": visitor.calls[:2000],
                "entrypoint": visitor.entrypoint,
                "framework_indicators": indicators,
            })
        except (SyntaxError, OSError) as exc:
            parse_errors.append({"path": str(relative), "error": str(exc)})
    entrypoints = [module["path"] for module in python_modules if module["entrypoint"] or any(x in module["framework_indicators"] for x in ["argparse", "click", "typer", "hydra", "fire"])]
    result = {
        "schema_version": 1,
        "generated_at": now(),
        "workspace": str(paths.workspace),
        "files_scanned": len(source_files),
        "language_counts": language_counts,
        "entrypoint_candidates": entrypoints,
        "python_modules": python_modules,
        "parse_errors": parse_errors,
        "limitations": [
            "静态调用边是基于 AST 的候选关系，动态分派、反射、注册器和配置驱动调用需结合运行日志确认。",
            "非 Python 文件当前只做文件与语言清单；语义调用链由 code-explainer 结合搜索、LSP 和运行证据补充。",
        ],
    }
    return result


def render_static_code_guide(index: dict[str, Any]) -> str:
    modules = index.get("python_modules") or []
    lines = [
        "# 代码静态结构索引",
        "",
        f"- 生成时间：`{index.get('generated_at')}`",
        f"- 扫描文件：`{index.get('files_scanned')}`",
        f"- Python 模块：`{len(modules)}`",
        "",
        "## 建议入口",
        "",
    ]
    for item in index.get("entrypoint_candidates") or []:
        lines.append(f"- `{item}`")
    if not index.get("entrypoint_candidates"):
        lines.append("- 暂未静态识别；需要结合 README、配置和运行命令判断。")
    lines.extend(["", "## 模块摘要", ""])
    for module in modules[:300]:
        lines.append(f"### `{module['path']}`")
        lines.append("")
        lines.append(f"- 函数：{len(module.get('functions') or [])}")
        lines.append(f"- 类：{len(module.get('classes') or [])}")
        lines.append(f"- 导入：{', '.join((module.get('imports') or [])[:12]) or '无'}")
        lines.append("")
    edges: list[tuple[str, str]] = []
    for module in modules:
        for call in module.get("calls") or []:
            caller, callee = call.get("caller", ""), call.get("callee", "")
            if caller and callee and len(edges) < 120:
                edges.append((caller, callee))
    lines.extend(["## 候选调用关系（静态、非完整）", "", "```mermaid", "flowchart LR"])
    def node_id(value: str) -> str:
        return "N" + hashlib.sha1(value.encode()).hexdigest()[:10]
    labels: dict[str, str] = {}
    for caller, callee in edges:
        labels[caller] = caller
        labels[callee] = callee
    for value, label in labels.items():
        safe = label.replace('"', "'")[:80]
        lines.append(f'  {node_id(value)}["{safe}"]')
    for caller, callee in edges:
        lines.append(f"  {node_id(caller)} --> {node_id(callee)}")
    lines.extend(["```", "", "> 该图只用于定位阅读起点；最终调用链应结合配置、注册器、运行日志和实际实验命令验证。", ""])
    return "\n".join(lines)


def cmd_code_index(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    ensure_workspace_layout(paths)
    try:
        run = current_run(paths)
        analysis_dir = run.analysis
        guide_dir = run.code_guide
    except ReproError:
        run = None
        analysis_dir = paths.state_home / "analysis"
        guide_dir = paths.state_home / "code-guide"
    index = build_code_index(paths)
    output = analysis_dir / "code_index.json"
    atomic_json(output, index)
    guide_dir.mkdir(parents=True, exist_ok=True)
    static_doc = guide_dir / "STATIC_STRUCTURE.md"
    static_doc.write_text(render_static_code_guide(index), encoding="utf-8")
    if run:
        event(run, "code.index.completed", output=str(output), files=index["files_scanned"])
    print(json.dumps({"code_index": str(output), "static_guide": str(static_doc), "entrypoints": index["entrypoint_candidates"]}, ensure_ascii=False, indent=2))
    return 0


def cmd_code_show(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    try:
        run = current_run(paths)
        index_path = run.analysis / "code_index.json"
        guide = run.code_guide
    except ReproError:
        index_path = paths.state_home / "analysis/code_index.json"
        guide = paths.state_home / "code-guide"
    result = {"index": str(index_path), "exists": index_path.exists(), "guide_dir": str(guide), "documents": []}
    if guide.exists():
        result["documents"] = [str(path) for path in sorted(guide.glob("*.md"))]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_secrets_init(args: argparse.Namespace) -> int:
    if SECRETS_FILE.exists() and not args.force:
        store = load_secrets_store()
        result = {"created": False, "path": str(SECRETS_FILE), "count": len(store["secrets"])}
    else:
        save_secrets_store(default_secrets_store())
        result = {"created": True, "path": str(SECRETS_FILE), "count": 0}
    if not args.quiet:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_secrets_set(args: argparse.Namespace) -> int:
    name = args.name.strip().upper()
    if not SECRET_NAME_RE.fullmatch(name):
        raise ReproError("Secret name must use uppercase letters, digits and underscores, and start with a letter")
    if args.stdin:
        value = sys.stdin.read().rstrip("\r\n")
    elif args.value is not None:
        value = args.value
    else:
        value = getpass.getpass(f"请输入 {name}（输入不会回显）：")
    if not value and not args.allow_empty:
        raise ReproError("Secret value is empty; use --allow-empty only when intentional")
    store = load_secrets_store() if SECRETS_FILE.exists() else default_secrets_store()
    store["secrets"][name] = value
    save_secrets_store(store)
    os.environ[name] = value
    print(json.dumps({"saved": True, "path": str(SECRETS_FILE), **secret_summary(name, value)}, ensure_ascii=False, indent=2))
    return 0


def cmd_secrets_unset(args: argparse.Namespace) -> int:
    name = args.name.strip().upper()
    store = load_secrets_store() if SECRETS_FILE.exists() else default_secrets_store()
    existed = name in store["secrets"]
    store["secrets"].pop(name, None)
    save_secrets_store(store)
    os.environ.pop(name, None)
    print(json.dumps({"removed": existed, "name": name, "path": str(SECRETS_FILE)}, ensure_ascii=False, indent=2))
    return 0


def cmd_secrets_list(args: argparse.Namespace) -> int:
    store = load_secrets_store() if SECRETS_FILE.exists() else default_secrets_store()
    rows = [secret_summary(name, value) for name, value in sorted(store["secrets"].items())]
    print(json.dumps({
        "path": str(SECRETS_FILE),
        "exists": SECRETS_FILE.exists(),
        "permissions": oct(SECRETS_FILE.stat().st_mode & 0o777) if SECRETS_FILE.exists() else None,
        "count": len(rows),
        "secrets": rows,
        "note": "Only names, lengths and fingerprints are shown; values are never printed.",
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_secrets_import_env(args: argparse.Namespace) -> int:
    names = list(args.name or [])
    if args.known:
        names.extend(KNOWN_SECRET_NAMES)
        routing = load_unified_config().get("model_routing", {}) or {}
        for profile in (routing.get("profiles", {}) or {}).values():
            if isinstance(profile, dict) and profile.get("api_key_env"):
                names.append(str(profile["api_key_env"]))
    names = sorted(set(name.strip().upper() for name in names if name.strip()))
    if not names:
        raise ReproError("Provide one or more NAME values, or use --known")
    store = load_secrets_store() if SECRETS_FILE.exists() else default_secrets_store()
    imported, missing = [], []
    for name in names:
        if not SECRET_NAME_RE.fullmatch(name):
            raise ReproError(f"Invalid secret name: {name}")
        value = os.environ.get(name, "")
        if value:
            store["secrets"][name] = value
            imported.append(name)
        else:
            missing.append(name)
    save_secrets_store(store)
    print(json.dumps({"imported": imported, "missing": missing, "path": str(SECRETS_FILE)}, ensure_ascii=False, indent=2))
    return 0


def cmd_secrets_edit(args: argparse.Namespace) -> int:
    if not SECRETS_FILE.exists():
        save_secrets_store(default_secrets_store())
    editor = args.editor or os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    command = shlex.split(editor) + [str(SECRETS_FILE)]
    code = subprocess.call(command)
    if code != 0:
        raise ReproError(f"Editor exited with status {code}")
    store = load_secrets_store()
    save_secrets_store(store)
    print(json.dumps({"edited": True, "path": str(SECRETS_FILE), "count": len(store["secrets"])}, ensure_ascii=False, indent=2))
    return 0


def cmd_secrets_clear(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ReproError("Refusing to delete all persisted secrets without --yes")
    config = load_unified_config()
    existed = bool(config.get("secrets"))
    names = list((config.get("secrets") or {}).keys())
    config["secrets"] = {}
    save_unified_config(config)
    for name in names:
        os.environ.pop(name, None)
    print(json.dumps({"deleted": existed, "path": str(UNIFIED_CONFIG_FILE), "note": "Model/MCP settings were preserved. OpenCode /connect credentials are stored separately and were not deleted."}, ensure_ascii=False, indent=2))
    return 0


def cmd_secrets_exec(args: argparse.Namespace) -> int:
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise ReproError("secrets exec requires a command after --")
    apply_persistent_secrets()
    os.execvpe(command[0], command, os.environ.copy())
    return 127


def cmd_config_show(args: argparse.Namespace) -> int:
    workspace_payload: dict[str, Any] | None = None
    try:
        paths = discover_workspace(args.workspace, args.state_root, args.latest)
        workspace_payload = {
            "root": str(paths.workspace),
            "config": str(paths.config),
            "model_routing": str(model_routing_file(paths, "workspace")),
        }
    except Exception as exc:
        workspace_payload = {"available": False, "reason": str(exc)}
    print(json.dumps({
        "global_config_home": str(PAPER_REPRO_CONFIG_HOME),
        "global": {
            "unified_config": str(UNIFIED_CONFIG_FILE),
            "contains": ["secrets", "model_routing", "mcp", "decision_policy", "decision_preferences", "self_improvement", "github_publish"],
            "generated_mcp_runtime": str(MCP_RUNTIME_CONFIG),
            "legacy_model_routing": str(MODEL_ROUTING_FILE),
            "legacy_mcp_settings": str(MCP_SETTINGS_FILE),
            "legacy_secrets": str(LEGACY_SECRETS_FILE),
        },
        "workspace": workspace_payload,
        "opencode_connect_credentials": str(Path.home() / ".local/share/opencode/auth.json"),
        "note": "OpenCode /connect credentials are outside paper-repro and are never deleted automatically.",
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_config_reset(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ReproError("Refusing to reset configuration without --yes")
    paths = None
    if args.scope in {"workspace", "all"}:
        paths = discover_workspace(args.workspace, args.state_root, args.latest)
    removed: list[str] = []
    if args.scope in {"global", "all"}:
        for target in [UNIFIED_CONFIG_FILE, LEGACY_SECRETS_FILE, MODEL_ROUTING_FILE, MCP_SETTINGS_FILE, MCP_RUNTIME_CONFIG]:
            if target.exists():
                target.unlink()
                removed.append(str(target))
        try:
            PAPER_REPRO_CONFIG_HOME.rmdir()
        except OSError:
            pass
    if args.scope in {"workspace", "all"} and paths is not None:
        for target in [paths.config, model_routing_file(paths, "workspace")]:
            if target.exists():
                target.unlink()
                removed.append(str(target))
    print(json.dumps({
        "reset": True,
        "scope": args.scope,
        "removed": removed,
        "preserved": [
            "项目运行记录与日志 (.paper-repro/runs)",
            "OpenCode /connect 凭据 (~/.local/share/opencode/auth.json)",
            "OpenCode 全局 provider 配置",
            "系统安装文件与项目 Conda 环境",
        ],
    }, ensure_ascii=False, indent=2))
    return 0


def default_mcp_settings() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "native_websearch": True,
        "servers": {
            "context7": {"enabled": True},
            "github-readonly": {"enabled": False},
            "huggingface": {"enabled": False},
            "brave-search": {"enabled": False},
        },
        "updated_at": now(),
    }


def load_mcp_settings() -> dict[str, Any]:
    defaults = default_mcp_settings()
    current = load_unified_config().get("mcp", {}) or {}
    result = dict(defaults)
    result["native_websearch"] = bool(current.get("native_websearch", defaults["native_websearch"]))
    result["servers"] = {}
    current_servers = current.get("servers", {}) if isinstance(current.get("servers", {}), dict) else {}
    for name in MCP_SERVER_ORDER:
        configured = current_servers.get(name, {}) if isinstance(current_servers.get(name, {}), dict) else {}
        result["servers"][name] = {"enabled": bool(configured.get("enabled", defaults["servers"][name]["enabled"]))}
    result["updated_at"] = current.get("updated_at", defaults["updated_at"])
    return result


def save_mcp_settings(settings: dict[str, Any]) -> None:
    settings = dict(settings)
    settings["updated_at"] = now()
    config = load_unified_config()
    config["mcp"] = settings
    save_unified_config(config)


def mcp_environment_status() -> dict[str, bool]:
    return {
        "CONTEXT7_API_KEY": bool(os.environ.get("CONTEXT7_API_KEY")),
        "GITHUB_MCP_TOKEN": bool(os.environ.get("GITHUB_MCP_TOKEN") or os.environ.get("GITHUB_TOKEN")),
        "HF_TOKEN": bool(os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")),
        "BRAVE_API_KEY": bool(os.environ.get("BRAVE_API_KEY") or os.environ.get("BRAVE_API_KEY_FILE")),
    }


def build_mcp_runtime_config(settings: dict[str, Any]) -> dict[str, Any]:
    env = mcp_environment_status()
    servers: dict[str, Any] = {}

    context7: dict[str, Any] = {
        "type": "remote",
        "url": "https://mcp.context7.com/mcp",
        "enabled": bool(settings["servers"]["context7"]["enabled"]),
        "timeout": 15000,
    }
    if env["CONTEXT7_API_KEY"]:
        context7["headers"] = {"Authorization": "Bearer {env:CONTEXT7_API_KEY}"}
    servers["context7"] = context7

    github_headers: dict[str, str] = {
        "X-MCP-Readonly": "true",
        "X-MCP-Toolsets": "repos,issues,pull_requests",
    }
    if os.environ.get("GITHUB_MCP_TOKEN"):
        github_headers["Authorization"] = "Bearer {env:GITHUB_MCP_TOKEN}"
    elif os.environ.get("GITHUB_TOKEN"):
        github_headers["Authorization"] = "Bearer {env:GITHUB_TOKEN}"
    servers["github-readonly"] = {
        "type": "remote",
        "url": "https://api.githubcopilot.com/mcp/readonly",
        "enabled": bool(settings["servers"]["github-readonly"]["enabled"]),
        "headers": github_headers,
        "timeout": 20000,
    }

    hf_headers: dict[str, str] = {}
    if os.environ.get("HF_TOKEN"):
        hf_headers["Authorization"] = "Bearer {env:HF_TOKEN}"
    elif os.environ.get("HUGGING_FACE_HUB_TOKEN"):
        hf_headers["Authorization"] = "Bearer {env:HUGGING_FACE_HUB_TOKEN}"
    huggingface: dict[str, Any] = {
        "type": "remote",
        "url": "https://huggingface.co/mcp?no_image_content=true",
        "enabled": bool(settings["servers"]["huggingface"]["enabled"]),
        "timeout": 20000,
    }
    if hf_headers:
        huggingface["headers"] = hf_headers
    servers["huggingface"] = huggingface

    brave_environment: dict[str, str] = {
        "BRAVE_MCP_ENABLED_TOOLS": "brave_web_search brave_news_search brave_llm_context",
    }
    if os.environ.get("BRAVE_API_KEY_FILE"):
        brave_environment["BRAVE_API_KEY_FILE"] = "{env:BRAVE_API_KEY_FILE}"
    elif os.environ.get("BRAVE_API_KEY"):
        brave_environment["BRAVE_API_KEY"] = "{env:BRAVE_API_KEY}"
    servers["brave-search"] = {
        "type": "local",
        "command": ["npx", "-y", "@brave/brave-search-mcp-server@2.1.0", "--transport", "stdio"],
        "enabled": bool(settings["servers"]["brave-search"]["enabled"]),
        "environment": brave_environment,
        "timeout": 20000,
    }

    return {
        "$schema": "https://opencode.ai/config.json",
        "mcp": servers,
    }


def sync_mcp_runtime_config(settings: dict[str, Any] | None = None) -> Path:
    settings = settings or load_mcp_settings()
    MCP_RUNTIME_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(MCP_RUNTIME_CONFIG, build_mcp_runtime_config(settings))
    return MCP_RUNTIME_CONFIG


def mcp_status_payload() -> dict[str, Any]:
    settings = load_mcp_settings()
    runtime = sync_mcp_runtime_config(settings)
    env = mcp_environment_status()
    servers = []
    descriptions = {
        "context7": "公共依赖和框架的最新文档；默认启用，API Key 可选但可提高限额。",
        "github-readonly": "GitHub Release、Issue、PR 和仓库元数据；严格只读。",
        "huggingface": "模型、数据集、论文和 Hub 文档检索；默认不开启写入/Job 工具。",
        "brave-search": "备用网页搜索 MCP；仅在需要第二搜索源且已配置 Brave API Key 时启用。",
    }
    required = {
        "context7": "可匿名低限额；建议 CONTEXT7_API_KEY",
        "github-readonly": "GITHUB_MCP_TOKEN/GITHUB_TOKEN，或在 OpenCode 中完成 OAuth",
        "huggingface": "HF_TOKEN/HUGGING_FACE_HUB_TOKEN，或在 OpenCode 中完成 OAuth",
        "brave-search": "BRAVE_API_KEY 或 BRAVE_API_KEY_FILE",
    }
    for name in MCP_SERVER_ORDER:
        servers.append({
            "name": name,
            "enabled": settings["servers"][name]["enabled"],
            "description": descriptions[name],
            "authentication": required[name],
        })
    return {
        "native_websearch": {
            "enabled": settings["native_websearch"],
            "implementation": "OpenCode 内建 websearch（Exa）",
            "api_key_required": False,
            "launch_env": "OPENCODE_ENABLE_EXA=1",
            "note": "网页发现优先使用内建工具，不额外占用 MCP 工具上下文。",
        },
        "runtime_config": str(runtime),
        "settings_file": str(UNIFIED_CONFIG_FILE),
        "launcher_config_note": "paper-opencode 会在 OPENCODE_CONFIG 未预设时加载该运行配置；项目 opencode.json 仍可覆盖。",
        "existing_OPENCODE_CONFIG": os.environ.get("OPENCODE_CONFIG", ""),
        "environment": env,
        "servers": servers,
        "usage_order": [
            "网页发现：内建 websearch；已知 URL：内建 webfetch。",
            "依赖/API 文档：Context7。",
            "仓库 Issue/PR/Release：GitHub read-only。",
            "模型、数据集和 Hub 论文：Hugging Face。",
            "内建搜索不可用或需要第二来源：Brave Search MCP。",
        ],
    }


def cmd_mcp_install_basic(args: argparse.Namespace) -> int:
    settings = load_mcp_settings()
    settings["native_websearch"] = not bool(args.no_native_websearch)
    settings["servers"]["context7"]["enabled"] = not bool(args.no_context7)
    if args.github or args.all_available:
        settings["servers"]["github-readonly"]["enabled"] = True
    if args.huggingface or args.all_available:
        settings["servers"]["huggingface"]["enabled"] = True
    if args.brave_search or args.all_available:
        settings["servers"]["brave-search"]["enabled"] = True
    save_mcp_settings(settings)
    sync_mcp_runtime_config(settings)
    payload = mcp_status_payload()
    payload["message"] = "基础联网能力已安装；重启 paper-opencode 后生效。"
    if not args.quiet:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_mcp_enable(args: argparse.Namespace) -> int:
    settings = load_mcp_settings()
    name = args.name
    if name == "native-websearch":
        settings["native_websearch"] = True
    elif name in MCP_SERVER_ORDER:
        settings["servers"][name]["enabled"] = True
    else:
        raise ReproError(f"Unknown MCP capability: {name}")
    save_mcp_settings(settings)
    sync_mcp_runtime_config(settings)
    print(json.dumps(mcp_status_payload(), ensure_ascii=False, indent=2))
    return 0


def cmd_mcp_disable(args: argparse.Namespace) -> int:
    settings = load_mcp_settings()
    name = args.name
    if name == "native-websearch":
        settings["native_websearch"] = False
    elif name in MCP_SERVER_ORDER:
        settings["servers"][name]["enabled"] = False
    else:
        raise ReproError(f"Unknown MCP capability: {name}")
    save_mcp_settings(settings)
    sync_mcp_runtime_config(settings)
    print(json.dumps(mcp_status_payload(), ensure_ascii=False, indent=2))
    return 0


def cmd_mcp_sync(args: argparse.Namespace) -> int:
    path = sync_mcp_runtime_config()
    if not args.quiet:
        print(json.dumps({"runtime_config": str(path), "synced": True}, ensure_ascii=False, indent=2))
    return 0


def cmd_mcp_status(args: argparse.Namespace) -> int:
    print(json.dumps(mcp_status_payload(), ensure_ascii=False, indent=2))
    return 0


def cmd_mcp_recommend(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    result = mcp_status_payload()
    result.update({
        "principle": "优先使用 OpenCode 内建工具；只添加对论文复现有明确增益的少量只读 MCP。",
        "recommended": [
            {
                "name": "native-websearch",
                "use": "基础网页发现。由 OpenCode 内建 Exa websearch 提供，无需 API Key，也无需额外 MCP。",
                "default": "enabled",
            },
            {
                "name": "context7",
                "use": "查询依赖的当前官方文档和特定版本 API。",
                "default": "enabled",
            },
            {
                "name": "github-readonly",
                "use": "读取 Release、Issue、PR 与仓库元数据。",
                "default": "opt-in/read-only",
            },
            {
                "name": "huggingface",
                "use": "检索模型、数据集、论文和 Hub 文档。",
                "default": "opt-in/read-only discovery",
            },
            {
                "name": "brave-search",
                "use": "内建 websearch 的备用搜索源；仅启用 web/news/LLM-context 三个工具。",
                "default": "optional fallback",
            },
        ],
        "not_recommended_by_default": [
            "filesystem MCP：与 OpenCode 内建文件工具重复。",
            "shell/terminal MCP：与 Bash 工具重复并扩大执行面。",
            "Memory MCP：长期状态已由 JSON、Markdown 和日志持久化。",
            "来源不明的论文/ArXiv MCP：优先官方论文 URL、Crossref/arXiv API 或 Hugging Face 官方 MCP。",
        ],
        "template": str(SYSTEM_HOME / "configs/opencode.mcp.basic.jsonc"),
        "workspace": str(paths.workspace),
    })
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def configured_execution_env(paths: WorkspacePaths, fallback_active: bool = False) -> dict[str, Any] | None:
    config = workspace_config(paths)
    configured = config.get("execution_env")
    if configured:
        prefix = Path(str(configured.get("prefix", ""))).expanduser().resolve()
        if not prefix.exists():
            raise ReproError(
                f"Configured project Conda environment does not exist: {prefix}\n"
                "Select another environment with: paper-repro env use --name <ENV>"
            )
        result = dict(configured)
        result["prefix"] = str(prefix)
        result.setdefault("name", prefix.name)
        result.setdefault("python", str(prefix / "bin/python"))
        result["role"] = "project"
        result["configured"] = True
        return result
    if fallback_active:
        active = active_conda_info()
        active["role"] = "project-fallback"
        active["configured"] = False
        return active
    return None


def pipeline_state() -> dict[str, Any]:
    steps = [
        {"index": index, "id": step_id, "name": name, "status": "pending"}
        for index, step_id, name in STANDARD_PIPELINE
    ]
    return {
        "total_steps": len(steps),
        "current_step": 1,
        "completed_steps": 0,
        "remaining_steps": len(steps),
        "steps": steps,
    }


def recalculate_pipeline(pipeline: dict[str, Any]) -> dict[str, Any]:
    steps = pipeline.get("steps", [])
    completed = len([step for step in steps if step.get("status") == "completed"])
    running = [step for step in steps if step.get("status") == "running"]
    pending = [step for step in steps if step.get("status") == "pending"]
    if running:
        current = int(running[0].get("index", completed + 1))
    elif pending:
        current = int(pending[0].get("index", completed + 1))
    else:
        current = len(steps)
    pipeline["total_steps"] = len(steps)
    pipeline["current_step"] = current
    pipeline["completed_steps"] = completed
    pipeline["remaining_steps"] = max(0, len(steps) - completed)
    return pipeline


def progress_from_pipeline(state: dict[str, Any], task_fraction: float | None = None) -> float:
    pipeline = recalculate_pipeline(state.get("pipeline") or pipeline_state())
    total = max(1, int(pipeline.get("total_steps", 1)))
    completed = int(pipeline.get("completed_steps", 0))
    fraction = max(0.0, min(1.0, task_fraction or 0.0))
    return min(1.0, (completed + fraction) / total)


def format_bytes(value: float | int | None) -> str:
    if value is None:
        return "unknown"
    size = float(value)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def environment_banner(paths: WorkspacePaths, run: RunPaths | None = None) -> str:
    control = active_conda_info()
    project = configured_execution_env(paths)
    lines = [
        "=" * 78,
        f"WORKSPACE      : {paths.workspace}",
        f"CONTROL CONDA  : {control['name']} ({control['prefix'] or 'inactive'})",
    ]
    if project:
        lines.append(f"PROJECT CONDA  : {project['name']} ({project['prefix']}) [configured]")
    else:
        lines.append("PROJECT CONDA  : NOT CONFIGURED (project commands are blocked)")
    if run:
        state = read_json(run.state, {}) or {}
        pipeline = recalculate_pipeline(state.get("pipeline") or pipeline_state())
        lines.append(
            f"RUN / STEP     : {run.root.name} / {pipeline['current_step']}/{pipeline['total_steps']} "
            f"(remaining {pipeline['remaining_steps']})"
        )
    lines.append("=" * 78)
    return "\n".join(lines)


def gpu_rows() -> list[dict[str, str]]:
    if not shutil.which("nvidia-smi"):
        return []
    query = "index,name,uuid,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"
    out = capture(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"])
    if out.startswith("unavailable:"):
        return []
    keys = ["index", "name", "uuid", "util_gpu_pct", "memory_used_mb", "memory_total_mb", "temperature_c", "power_w"]
    rows: list[dict[str, str]] = []
    for line in out.splitlines():
        values = [value.strip() for value in line.split(",")]
        if len(values) == len(keys):
            rows.append(dict(zip(keys, values)))
    return rows


def ensure_workspace_layout(paths: WorkspacePaths) -> None:
    paths.state_home.mkdir(parents=True, exist_ok=True)
    paths.runs.mkdir(parents=True, exist_ok=True)
    paths.system.mkdir(parents=True, exist_ok=True)
    for subdir in ["hf", "torch", "datasets", "models", "downloads"]:
        (paths.cache / subdir).mkdir(parents=True, exist_ok=True)
    ignore = paths.state_home / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n!.gitignore\n", encoding="utf-8")


def ensure_run_layout(run: RunPaths) -> None:
    for directory in [run.meta, run.analysis, run.assets, run.environment, run.logs, run.results, run.report, run.code_guide, run.runtime]:
        directory.mkdir(parents=True, exist_ok=True)
    compatibility = {
        "manifest.json": "meta/manifest.json",
        "state.json": "meta/state.json",
        "commands.jsonl": "execution/commands.jsonl",
        "gpu.csv": "execution/gpu.csv",
        "logs": "execution/logs",
        "artifacts.jsonl": "assets/artifacts.jsonl",
        "paper_manifest.json": "analysis/paper_manifest.json",
        "repo_manifest.json": "analysis/repo_manifest.json",
        "reproduction_matrix.json": "analysis/reproduction_matrix.json",
        "assets.lock.json": "assets/assets.lock.json",
        "report.md": "report/report.md",
        "summary.json": "report/summary.json",
        "RUN_BLOCKERS.md": "report/RUN_BLOCKERS.md",
        "RUN_ISSUES.md": "report/RUN_BLOCKERS.md",
        "DECISIONS.md": "report/DECISIONS.md",
    }
    for link_name, target in compatibility.items():
        link = run.root / link_name
        if link.exists() or link.is_symlink():
            continue
        try:
            link.symlink_to(target)
        except OSError:
            pass


def event(run: RunPaths, event_type: str, **payload: Any) -> None:
    append_jsonl(run.events, {"ts": now(), "type": event_type, **payload})


def issue_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def folded_issues(records: list[dict[str, Any]], id_field: str = "issue_id") -> list[dict[str, Any]]:
    folded: dict[str, dict[str, Any]] = {}
    for record in records:
        record_id = record.get(id_field) or record.get("issue_id") or record.get("blocker_id")
        if not record_id:
            continue
        if record.get("action", "opened") == "opened":
            folded[record_id] = dict(record)
            folded[record_id]["status"] = "open"
        elif record_id in folded:
            folded[record_id].update({
                "status": record.get("status", "resolved"),
                "resolved_at": record.get("ts"),
                "resolution": record.get("resolution", ""),
            })
    return sorted(folded.values(), key=lambda item: item.get("ts", ""), reverse=True)


def render_issue_markdown(path: Path, title: str, records: list[dict[str, Any]], *, kind: str = "system") -> None:
    id_field = "blocker_id" if kind == "blocker" else "issue_id"
    items = folded_issues(records, id_field=id_field)
    open_count = sum(1 for item in items if item.get("status") == "open")
    noun = "阻塞项" if kind == "blocker" else "系统问题"
    empty = "当前没有记录到项目复现阻塞项。" if kind == "blocker" else "当前没有记录到系统功能问题。"
    lines = [
        f"# {title}",
        "",
        f"- 系统版本：`{SYSTEM_VERSION}`",
        f"- 生成时间：`{now()}`",
        f"- {noun}总数：`{len(items)}`",
        f"- 未解决：`{open_count}`",
        "",
    ]
    if kind == "system":
        lines.extend([
            "> 本文档只汇总 paper-repro / OpenCode 集成本身能否正常工作、可观测性、安全性和优化空间。",
            "> 某一论文仓库的依赖冲突、数据缺失、训练报错等项目问题记录在本次 Run 的 `RUN_BLOCKERS.md`，不会默认进入系统反馈包。",
            "",
        ])
    if not items:
        lines.extend([empty, ""])
    for item in items:
        record_id = item.get(id_field) or item.get("issue_id") or item.get("blocker_id")
        lines.extend([
            f"## {record_id} · {item.get('title', '未命名')}",
            "",
            f"- 状态：`{item.get('status', 'open')}`",
            f"- 严重度：`{item.get('severity', 'error')}`",
            f"- 组件：`{item.get('component', 'unknown')}`",
            f"- 类别：`{item.get('category', '')}`",
            f"- 阶段：`{item.get('stage', '')}`",
            f"- 时间：`{item.get('ts', '')}`",
            "",
            "### 现象",
            "",
            item.get("details", "") or item.get("title", ""),
            "",
        ])
        if item.get("expected"):
            lines.extend(["### 期望行为", "", item["expected"], ""])
        if item.get("optimization"):
            lines.extend(["### 优化建议", "", item["optimization"], ""])
        if item.get("command"):
            lines.extend(["### 相关命令", "", f"```bash\n{item['command']}\n```", ""])
        if item.get("log"):
            lines.extend([f"- 日志：`{item['log']}`", ""])
        if item.get("resolution"):
            lines.extend(["### 处理结果", "", item["resolution"], ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def record_system_issue(
    paths: WorkspacePaths | None,
    run: RunPaths | None,
    *,
    title: str,
    details: str,
    severity: str = "error",
    component: str = "reproctl",
    category: str = "system-function",
    stage: str = "",
    command: str = "",
    log: str = "",
    expected: str = "",
    optimization: str = "",
    issue_id: str | None = None,
) -> dict[str, Any]:
    record = {
        "action": "opened",
        "scope": "system",
        "issue_id": issue_id or f"SYS-{local_stamp()}-{uuid.uuid4().hex[:6]}",
        "ts": now(),
        "system_version": SYSTEM_VERSION,
        "severity": severity,
        "component": component,
        "category": category,
        "stage": stage,
        "title": title,
        "details": redact(details),
        "expected": redact(expected),
        "optimization": redact(optimization),
        "command": redact(command),
        "log": log,
        "workspace": str(paths.workspace) if paths else "",
        "run_id": run.root.name if run else "",
        "conda_env": os.environ.get("CONDA_DEFAULT_ENV", ""),
        "python": sys.executable,
    }
    append_jsonl(GLOBAL_ISSUES, record)
    if paths:
        append_jsonl(paths.system / "issues.jsonl", record)
        render_issue_markdown(
            paths.system / "SYSTEM_ISSUES.md",
            "系统功能与优化问题汇总",
            issue_records(paths.system / "issues.jsonl"),
            kind="system",
        )
    if run:
        event(run, "system.issue.opened", issue_id=record["issue_id"], severity=severity, title=title)
    try:
        record["improvement_id"] = enqueue_system_issue_candidate(record)
    except Exception as exc:
        record["improvement_enqueue_error"] = redact(str(exc))
    return record


def record_blocker(
    paths: WorkspacePaths,
    run: RunPaths,
    *,
    title: str,
    details: str,
    severity: str = "error",
    component: str = "project",
    stage: str = "",
    command: str = "",
    log: str = "",
    blocker_id: str | None = None,
) -> dict[str, Any]:
    record = {
        "action": "opened",
        "scope": "project",
        "blocker_id": blocker_id or f"BLOCK-{local_stamp()}-{uuid.uuid4().hex[:6]}",
        "ts": now(),
        "system_version": SYSTEM_VERSION,
        "severity": severity,
        "component": component,
        "stage": stage,
        "title": title,
        "details": redact(details),
        "command": redact(command),
        "log": log,
        "workspace": str(paths.workspace),
        "run_id": run.root.name,
    }
    append_jsonl(run.blockers, record)
    render_issue_markdown(
        run.report / "RUN_BLOCKERS.md",
        "本次论文复现阻塞项",
        issue_records(run.blockers),
        kind="blocker",
    )
    event(run, "project.blocker.opened", blocker_id=record["blocker_id"], severity=severity, title=title)
    rte.emit_event(_runtime_paths(paths, run), "blocker.created", data={
        "blocker_id": record["blocker_id"], "severity": severity, "title": title, "stage": record.get("stage"),
    })
    return record


# Compatibility wrapper for older tool calls. New code should call one of the two explicit functions.
def record_issue(paths: WorkspacePaths | None, run: RunPaths | None, **kwargs: Any) -> dict[str, Any]:
    scope = kwargs.pop("scope", "system")
    if scope == "project":
        if paths is None or run is None:
            raise ReproError("Project blocker requires a workspace and current run")
        return record_blocker(paths, run, **kwargs)
    return record_system_issue(paths, run, **kwargs)

def system_manifest(paths: WorkspacePaths, repository: str, paper: str, run: RunPaths) -> dict[str, Any]:
    prefix, env_name = active_conda()
    conda_explicit = capture(["conda", "list", "--explicit"], cwd=paths.workspace, timeout=60)
    pip_freeze = capture([sys.executable, "-m", "pip", "freeze"], cwd=paths.workspace, timeout=60)
    nvidia = capture(["nvidia-smi", "-q"], cwd=paths.workspace, timeout=30)
    git_status = capture(["git", "status", "--porcelain=v1"], cwd=paths.workspace)
    (run.environment / "conda-explicit.txt").write_text(conda_explicit + "\n", encoding="utf-8")
    (run.environment / "pip-freeze.txt").write_text(pip_freeze + "\n", encoding="utf-8")
    (run.environment / "nvidia-smi.txt").write_text(nvidia + "\n", encoding="utf-8")
    (run.environment / "git-status.txt").write_text(git_status + "\n", encoding="utf-8")
    return {
        "schema_version": 2,
        "system_version": SYSTEM_VERSION,
        "created_at": now(),
        "repository": repository,
        "paper": paper,
        "workspace": str(paths.workspace),
        "state_home": str(paths.state_home),
        "run_path": str(run.root),
        "host": platform.node(),
        "platform": platform.platform(),
        "kernel": platform.release(),
        "python": sys.version,
        "python_executable": sys.executable,
        "conda_prefix": prefix,
        "conda_env": env_name,
        "git_root": str(git_root(paths.workspace) or ""),
        "git_commit": capture(["git", "rev-parse", "HEAD"], cwd=paths.workspace),
        "nvcc": capture(["nvcc", "--version"], cwd=paths.workspace) if shutil.which("nvcc") else "unavailable",
        "disk": capture(["df", "-h", str(paths.workspace)], cwd=paths.workspace),
        "gpus": gpu_rows(),
        "files": {
            "conda_explicit": "environment/conda-explicit.txt",
            "pip_freeze": "environment/pip-freeze.txt",
            "nvidia_smi": "environment/nvidia-smi.txt",
            "git_status": "environment/git-status.txt",
        },
    }


def set_current(paths: WorkspacePaths, run: Path) -> None:
    if paths.current.exists() or paths.current.is_symlink():
        if paths.current.is_dir() and not paths.current.is_symlink():
            raise ReproError(f"Cannot replace directory: {paths.current}")
        paths.current.unlink()
    paths.current_txt.unlink(missing_ok=True)
    try:
        paths.current.symlink_to(Path(os.path.relpath(run, paths.state_home)))
    except OSError:
        paths.current_txt.write_text(str(run), encoding="utf-8")


def cmd_init(args: argparse.Namespace) -> int:
    active_conda()
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    ensure_workspace_layout(paths)
    config_existed = paths.config.exists()
    if not config_existed:
        config = workspace_config(paths)
        config["created_at"] = now()
        config["workspace_id"] = "ws-" + uuid.uuid4().hex[:12]
        save_workspace_config(paths, config)
    else:
        _workspace_id(paths)  # migrate and persist the v2.1 path-derived ID once
    run_id = local_stamp() + "-" + uuid.uuid4().hex[:8]
    run = RunPaths(paths.runs / run_id)
    ensure_run_layout(run)
    runtime = rte.RuntimePaths(run.root)
    runtime.ensure()
    # GPU pool is intentionally NOT auto-confirmed. Each run asks once before GPU tasks start.
    initial_gpu_policy = rte.default_gpu_policy()
    defaults = _runtime_workspace_defaults(paths)
    if defaults.get("default_gpu_ids"):
        initial_gpu_policy["allowed_gpu_ids"] = list(defaults["default_gpu_ids"])
        initial_gpu_policy["selection_source"] = "workspace-suggestion"
    if defaults.get("max_parallel_tasks") is not None:
        initial_gpu_policy.setdefault("scheduler", {})["max_parallel_tasks"] = int(defaults["max_parallel_tasks"])
    atomic_json(runtime.gpu_policy, initial_gpu_policy)
    atomic_json(run.manifest, system_manifest(paths, args.repository, args.paper, run))
    control_env = active_conda_info()
    project_env = configured_execution_env(paths)
    atomic_json(run.state, {
        "schema_version": 2,
        "system_version": SYSTEM_VERSION,
        "run_id": run_id,
        "workspace": str(paths.workspace),
        "state_home": str(paths.state_home),
        "status": "initialized",
        "stage": "paper-audit",
        "progress": 0.0,
        "message": "复现运行已创建，准备开始第 1/8 步",
        "started_at": now(),
        "updated_at": now(),
        "elapsed_seconds": 0,
        "eta_seconds": None,
        "pipeline": pipeline_state(),
        "task": {
            "name": "",
            "status": "idle",
            "progress": 0.0,
            "completed": 0,
            "total": None,
            "unit": "",
            "speed": None,
            "eta_seconds": None,
        },
        "control_env": control_env,
        "execution_env": project_env,
        "last_gpu": gpu_rows(),
        "blockers": [],
        "pending_decision_count": 0,
        "decision_policy": decision_policy(paths),
    })
    set_current(paths, run.root)
    atomic_json(paths.enabled, {"enabled_at": now(), "workspace": str(paths.workspace), "run_id": run_id, "system_version": SYSTEM_VERSION})
    register_workspace(paths, run.root)
    event(run, "run.created", repository=args.repository, paper=args.paper)
    rte.emit_event(runtime, "run.started", data={"stage": "paper-audit"})
    render_issue_markdown(run.report / "RUN_BLOCKERS.md", "本次论文复现阻塞项", [], kind="blocker")
    render_decisions_markdown(run)
    render_issue_markdown(paths.system / "SYSTEM_ISSUES.md", "系统功能与优化问题汇总", issue_records(paths.system / "issues.jsonl"), kind="system")
    print(json.dumps({
        "run_id": run_id,
        "workspace": str(paths.workspace),
        "state_home": str(paths.state_home),
        "path": str(run.root),
        "control_env": control_env,
        "execution_env": project_env,
        "pipeline_steps": len(STANDARD_PIPELINE),
        "decision_mode": decision_policy(paths).get("mode"),
        "status_command": f"paper-repro --workspace {shlex.quote(str(paths.workspace))} status --watch",
    }, ensure_ascii=False, indent=2))
    return 0


def safe_command(command: str) -> None:
    active_conda()
    for rule in BLOCKED:
        if rule.search(command):
            raise ReproError(f"Blocked dangerous command: {command}")


def update_state(run: RunPaths, **changes: Any) -> None:
    state = read_json(run.state, {})
    if not state:
        raise ReproError(f"Missing state file: {run.state}")
    state.update(changes)
    state["updated_at"] = now()
    started = datetime.fromisoformat(state["started_at"])
    state["elapsed_seconds"] = int((datetime.now(timezone.utc) - started).total_seconds())
    state["last_gpu"] = gpu_rows()
    atomic_json(run.state, state)


def monitor_gpu(path: Path, stop: threading.Event, interval: float = 5.0) -> None:
    header_written = path.exists() and path.stat().st_size > 0
    while not stop.is_set():
        rows = gpu_rows()
        if rows:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", newline="", encoding="utf-8") as f:
                fieldnames = ["ts", *rows[0].keys()]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not header_written:
                    writer.writeheader()
                    header_written = True
                for row in rows:
                    writer.writerow({"ts": now(), **row})
        stop.wait(interval)


def execution_argv(paths: WorkspacePaths, command: str) -> tuple[list[str], dict[str, Any]]:
    project = configured_execution_env(paths)
    if project is None:
        raise DecisionPendingError(
            "Project Conda environment is not configured. Project commands are blocked to protect the control environment.\n"
            "Create one with: paper-repro env create --name <ENV> --python <VERSION>\n"
            "Or select one with: paper-repro env use --name <ENV>"
        )
    control_prefix = str(Path(os.environ.get("CONDA_PREFIX", "")).expanduser().resolve())
    project_prefix = str(Path(project["prefix"]).expanduser().resolve())
    if project.get("name") == "base":
        raise ReproError("Project execution environment cannot be Conda base")
    if project_prefix == control_prefix:
        return ["bash", "-lc", command], project
    conda = conda_executable()
    return [conda, "run", "--no-capture-output", "-p", project_prefix, "bash", "-lc", command], project


def cmd_exec(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    safe_command(args.command)
    run = current_run(paths)
    blocked = pending_decisions(run, blocking_only=True)
    if blocked:
        titles = "；".join(str(item.get("title", item.get("decision_id"))) for item in blocked[:5])
        raise DecisionPendingError(
            f"当前有 {len(blocked)} 项待确认决策，已阻止执行项目命令：{titles}\n"
            "查看：paper-repro decisions checkpoint\n"
            "确认：paper-repro decisions resolve <DECISION_ID> --option <OPTION_ID>"
        )
    ensure_run_layout(run)
    argv, project_env = execution_argv(paths, args.command)
    control_env = active_conda_info()
    print(environment_banner(paths, run), flush=True)
    command_id = datetime.now().strftime("%H%M%S") + "-" + uuid.uuid4().hex[:6]
    stage_slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", args.stage)[:80]
    log_path = run.logs / f"{command_id}-{stage_slug}.log"
    started = time.time()
    estimate = args.estimate if args.estimate > 0 else None
    state_before = read_json(run.state, {}) or {}
    task = {
        "name": args.stage,
        "status": "running",
        "progress": 0.0,
        "completed": 0,
        "total": None,
        "unit": "items",
        "speed": None,
        "eta_seconds": estimate,
        "started_at": now(),
    }
    update_state(
        run,
        status="running",
        stage=args.stage,
        message="命令已开始执行",
        eta_seconds=estimate,
        control_env=control_env,
        execution_env=project_env,
        task=task,
        progress=progress_from_pipeline(state_before, 0.0),
    )
    start_record = {
        "record_type": "start",
        "id": command_id,
        "stage": args.stage,
        "command": redact(args.command),
        "cwd": str(paths.workspace),
        "started_at": now(),
        "status": "running",
        "log": str(log_path.relative_to(run.root)),
        "timeout_seconds": args.timeout,
        "estimate_seconds": estimate,
        "control_env": control_env,
        "execution_env": project_env,
        "argv": [redact(item) for item in argv],
    }
    append_jsonl(run.commands, start_record)
    event(run, "command.started", **start_record)

    stop = threading.Event()
    watcher = threading.Thread(target=monitor_gpu, args=(run.gpu, stop), daemon=True)
    watcher.start()

    sec_policy = execution_security_policy(paths)
    sandbox_policy = task_sandbox_policy(paths)
    if str(sandbox_policy.get("mode", "auto")) != "trusted-off" and not rte.sandbox_backend_status().get("available"):
        raise DecisionPendingError(
            "短时项目命令同样要求 OS 沙箱，但当前未检测到 bwrap。"
            "安装后重试；仅对已审查仓库可由用户显式设置 trusted-off。"
        )
    requested_secret_env = _validate_task_secret_env(paths, args.secret_env or [])
    env = sec.scrub_environment(os.environ.copy(), allow_names=requested_secret_env)
    for name in requested_secret_env:
        if name in os.environ:
            env[name] = os.environ[name]
    env.update({
        "REPRO_WORKSPACE": str(paths.workspace),
        "REPRO_STATE_HOME": str(paths.state_home),
        "REPRO_RUN_DIR": str(run.root),
    })
    env.setdefault("HF_HOME", str(paths.cache / "hf"))
    env.setdefault("HUGGINGFACE_HUB_CACHE", str(paths.cache / "hf/hub"))
    env.setdefault("TORCH_HOME", str(paths.cache / "torch"))
    env.setdefault("XDG_CACHE_HOME", str(paths.cache))
    env.setdefault("WANDB_MODE", "offline")
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    sandbox_spec = {
        "task_id": f"CMD-{command_id}",
        "workspace": str(paths.workspace),
        "execution_env": project_env,
        "sandbox": sandbox_policy,
    }
    argv, sandbox_state = rte.build_sandbox_argv(rte.RuntimePaths(run.root), sandbox_spec, argv, env, [])
    start_record["sandbox"] = sandbox_state

    proc = subprocess.Popen(
        argv,
        cwd=paths.workspace,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    timed_out = False
    code = 1
    try:
        with log_path.open("w", encoding="utf-8") as log:
            log.write(
                f"# paper-repro command log\n"
                f"# run_id={run.root.name}\n"
                f"# stage={args.stage}\n"
                f"# cwd={paths.workspace}\n"
                f"# control_conda={control_env['name']} ({control_env['prefix']})\n"
                f"# project_conda={project_env['name']} ({project_env['prefix']})\n"
                f"# started_at={now()}\n"
                f"# command={redact(args.command)}\n\n"
            )
            assert proc.stdout is not None
            while True:
                if time.time() - started > args.timeout:
                    timed_out = True
                    os.killpg(proc.pid, signal.SIGTERM)
                    break
                line = proc.stdout.readline()
                if line:
                    safe_line = redact(line)
                    sys.stdout.write(safe_line)
                    sys.stdout.flush()
                    log.write(safe_line)
                    log.flush()
                    match = PROGRESS.search(safe_line)
                    if match:
                        current, total = float(match.group(1)), float(match.group(2))
                        fraction = 0.0 if total <= 0 else max(0.0, min(1.0, current / total))
                        elapsed = time.time() - started
                        eta = int(elapsed * (1 - fraction) / fraction) if fraction > 0 else estimate
                        speed = current / elapsed if elapsed > 0 else None
                        state_now = read_json(run.state, {}) or {}
                        task_now = dict(state_now.get("task") or task)
                        task_now.update({
                            "progress": fraction,
                            "completed": current,
                            "total": total,
                            "speed": speed,
                            "eta_seconds": eta,
                            "message": match.group(3).strip() or args.stage,
                        })
                        update_state(
                            run,
                            progress=progress_from_pipeline(state_now, fraction),
                            message=match.group(3).strip() or args.stage,
                            eta_seconds=eta,
                            task=task_now,
                        )
                elif proc.poll() is not None:
                    break
                else:
                    time.sleep(0.1)
            if timed_out:
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
            code = proc.wait(timeout=20)
    finally:
        stop.set()
        watcher.join(timeout=2)

    elapsed = int(time.time() - started)
    status = "timeout" if timed_out else ("succeeded" if code == 0 else "failed")
    finish_record = {
        "record_type": "finish",
        "id": command_id,
        "stage": args.stage,
        "command": redact(args.command),
        "finished_at": now(),
        "status": status,
        "exit_code": code,
        "elapsed_seconds": elapsed,
        "log": str(log_path.relative_to(run.root)),
    }
    append_jsonl(run.commands, finish_record)
    event(run, "command.finished", **finish_record)
    final_state = read_json(run.state, {}) or {}
    old_progress = final_state.get("progress", 0.0)
    final_task = dict(final_state.get("task") or task)
    final_task.update({
        "status": status,
        "progress": 1.0 if code == 0 else final_task.get("progress", 0.0),
        "eta_seconds": 0 if code == 0 else None,
        "finished_at": now(),
    })
    update_state(
        run,
        status=status,
        stage=args.stage,
        progress=max(old_progress, progress_from_pipeline(final_state, 1.0)) if code == 0 else old_progress,
        message=f"命令{_zh_status(status)}",
        eta_seconds=0 if code == 0 else None,
        task=final_task,
        control_env=control_env,
        execution_env=project_env,
    )
    if code != 0 or timed_out:
        record_issue(
            paths,
            run,
            title=f"命令执行{status}",
            details=f"Stage {args.stage} exited with code {code}.",
            severity="error" if not timed_out else "warning",
            component="executor",
            stage=args.stage,
            command=args.command,
            log=str(log_path),
            scope="project",
        )
    print(json.dumps({
        "status": status,
        "exit_code": code,
        "elapsed_seconds": elapsed,
        "log": str(log_path),
        "workspace": str(paths.workspace),
        "run_id": run.root.name,
        "control_env": control_env,
        "execution_env": project_env,
    }, ensure_ascii=False, indent=2))
    return 0 if code == 0 and not timed_out else code or 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def cmd_register(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    target = (paths.workspace / args.path).resolve() if not Path(args.path).is_absolute() else Path(args.path).resolve()
    if not target.exists():
        raise FileNotFoundError(target)
    if target.is_file():
        size = target.stat().st_size
        digest = sha256_file(target)
    else:
        files = sorted(path for path in target.rglob("*") if path.is_file())
        size = sum(path.stat().st_size for path in files)
        hasher = hashlib.sha256()
        for path in files:
            hasher.update(str(path.relative_to(target)).encode())
            hasher.update(sha256_file(path).encode())
        digest = hasher.hexdigest()
    record = {
        "ts": now(),
        "run_id": run.root.name,
        "kind": args.kind,
        "path": str(target),
        "size_bytes": size,
        "sha256": digest,
        "source": args.source,
        "revision": args.revision,
    }
    append_jsonl(run.artifacts, record)
    event(run, "artifact.registered", **record)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


def status_dict(paths: WorkspacePaths, include_runtime: bool = True) -> dict[str, Any]:
    run = current_run(paths)
    state = read_json(run.state, {})
    if not state:
        raise ReproError(f"Invalid run state: {run.state}")
    state["run_path"] = str(run.root)
    state["workspace"] = str(paths.workspace)
    state["state_home"] = str(paths.state_home)
    state["control_env"] = active_conda_info()
    state["execution_env"] = configured_execution_env(paths)
    state["pipeline"] = recalculate_pipeline(state.get("pipeline") or pipeline_state())
    state["system_issue_count"] = len([item for item in folded_issues(issue_records(paths.system / "issues.jsonl"), id_field="issue_id") if item.get("status") == "open"])
    state["blocker_count"] = len([item for item in folded_issues(issue_records(run.blockers), id_field="blocker_id") if item.get("status") == "open"])
    pending = pending_decisions(run)
    state["pending_decision_count"] = len(pending)
    state["pending_decisions"] = pending[:5]
    state["decision_policy"] = decision_policy(paths)
    improvements = folded_improvements()
    state["self_improvement_count"] = len([item for item in improvements if item.get("status") not in {"discarded", "verified", "rolled-back"}])
    state["self_improvement_policy"] = self_improvement_policy()
    publications = folded_publications()
    state["publication_count"] = len([item for item in publications if item.get("status") not in {"published", "published-pr", "no-changes", "aborted"}])
    state["publication_target"] = _publish_target(github_publish_policy())
    state["issue_count"] = state["system_issue_count"]  # compatibility
    if include_runtime:
        try:
            runtime = _runtime_paths(paths, run)
            snapshot = rte.refresh_snapshot(runtime)
            state["runtime"] = snapshot
            state["scheduler"] = snapshot.get("scheduler") or {}
            state["gpu_pool"] = (snapshot.get("gpu") or {}).get("policy") or {}
            state["active_tasks"] = snapshot.get("active_tasks") or []
            state["queued_task_count"] = int((snapshot.get("queue") or {}).get("queued", 0))
            state["active_task_count"] = int((snapshot.get("queue") or {}).get("active", 0))
            # Keep the legacy single-task field useful for older clients.
            compat = (snapshot.get("active_tasks") or [])[:1]
            if not compat:
                compat = [t for t in snapshot.get("tasks", []) if t.get("state") in rte.QUEUE_STATES][:1]
            if compat:
                item = compat[0]
                prog = item.get("progress") or {}
                state["task"] = {
                    "name": item.get("display_name"),
                    "status": item.get("state"),
                    "progress": (float(prog.get("percent", 0.0)) / 100.0),
                    "completed": prog.get("current"),
                    "total": prog.get("total"),
                    "unit": prog.get("unit", ""),
                    "speed": prog.get("speed"),
                    "eta_seconds": prog.get("eta_seconds"),
                    "message": prog.get("message", ""),
                    "task_id": item.get("task_id"),
                    "gpu_ids": item.get("gpu_ids", []),
                }
        except Exception as exc:  # keep status available even if runtime metadata is damaged
            state["runtime_error"] = str(exc)
    return state


def _zh_status(value: Any) -> str:
    mapping = {
        "initialized": "已初始化", "running": "运行中", "pending": "等待中", "completed": "已完成",
        "failed": "失败", "blocked": "已阻塞", "succeeded": "成功", "timeout": "超时",
        "idle": "空闲", "unknown": "未知", "configured": "已配置", "awaiting-decision": "等待决策",
        "execution-complete": "执行完成，等待核验", "starting": "启动中",
        "waiting-resources": "等待资源", "waiting-dependencies": "等待前置任务",
        "cancelled": "已取消", "stale": "状态陈旧", "waiting-gpu-confirmation": "等待 GPU 确认",
        "external-busy": "外部任务占用", "available": "可调度", "assigned": "已分配", "not-allowed": "未授权调度",
    }
    return mapping.get(str(value), str(value))


def _format_seconds(value: Any) -> str:
    if value in (None, "", "None"):
        return "未知"
    try:
        total = int(float(value))
    except (TypeError, ValueError):
        return str(value)
    if total < 60:
        return f"{total} 秒"
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if hours:
        parts.append(f"{hours} 小时")
    if minutes:
        parts.append(f"{minutes} 分")
    if seconds and not hours:
        parts.append(f"{seconds} 秒")
    return " ".join(parts)


def cmd_status(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    if args.json:
        print(json.dumps(status_dict(paths), ensure_ascii=False, indent=2))
        return 0
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        while True:
            state = status_dict(paths)
            print(json.dumps(state, ensure_ascii=False, indent=2))
            if not args.watch:
                break
            time.sleep(args.interval)
        return 0

    console = Console()
    while True:
        state = status_dict(paths)
        pipeline = state.get("pipeline") or {}
        current_step = pipeline.get("current_step", "?")
        total_steps = pipeline.get("total_steps", "?")
        remaining = pipeline.get("remaining_steps", "?")
        table = Table(title=f"论文代码复现状态 · {state['run_id']} · 第 {current_step}/{total_steps} 步")
        table.add_column("项目")
        table.add_column("当前值")
        control = state.get("control_env") or {}
        project = state.get("execution_env") or {}
        table.add_row("工作区", str(state.get("workspace")))
        table.add_row("控制 Conda", f"{control.get('name')} · {control.get('prefix')}")
        table.add_row(
            "项目 Conda",
            (f"{project.get('name')} · {project.get('prefix')}【已配置】" if project else "未配置：项目 Python/训练命令已阻止"),
        )
        table.add_row("步骤", f"第 {current_step}/{total_steps} 步 · 剩余 {remaining} 步")
        progress = state.get("progress")
        progress_text = f"{progress * 100:.1f}%" if isinstance(progress, (int, float)) else str(progress)
        table.add_row("运行状态", _zh_status(state.get("status")))
        table.add_row("当前阶段", str(state.get("stage", "")))
        table.add_row("总体进度", progress_text)
        table.add_row("当前消息", str(state.get("message", "")))
        table.add_row("已运行时间", _format_seconds(state.get("elapsed_seconds")))
        table.add_row("预计剩余时间", _format_seconds(state.get("eta_seconds")))
        table.add_row("系统功能问题", str(state.get("system_issue_count", 0)))
        improve_policy = state.get("self_improvement_policy") or {}
        table.add_row("系统自我迭代", f"{SELF_IMPROVE_MODES.get(str(improve_policy.get('mode')), improve_policy.get('mode', ''))} · 待处理 {state.get('self_improvement_count', 0)} 项")
        table.add_row("GitHub 开源发布", f"待处理 {state.get('publication_count', 0)} 项 · 目标 {state.get('publication_target') or '尚未配置'}")
        table.add_row("项目复现阻塞项", str(state.get("blocker_count", 0)))
        policy = state.get("decision_policy") or {}
        mode_label = DECISION_MODES.get(str(policy.get("mode")), {}).get("label", str(policy.get("mode", "")))
        table.add_row("决策模式", f"{mode_label} · 待确认 {state.get('pending_decision_count', 0)} 项")
        runtime_state = state.get("runtime") or {}
        scheduler_state = runtime_state.get("scheduler") or {}
        queue_state = runtime_state.get("queue") or {}
        gpu_policy = (runtime_state.get("gpu") or {}).get("policy") or {}
        table.add_row("执行调度器", f"{_zh_status(scheduler_state.get('state', 'stopped'))} · PID {scheduler_state.get('pid') or '-'}")
        table.add_row("任务队列", f"总计 {queue_state.get('total', 0)} · 运行 {queue_state.get('active', 0)} · 等待 {queue_state.get('queued', 0)} · 成功 {queue_state.get('succeeded', 0)} · 失败 {queue_state.get('failed', 0)}")
        pool_ids = gpu_policy.get("allowed_gpu_ids", [])
        table.add_row("本次 GPU 资源池", (",".join(f"GPU{x}" for x in pool_ids) if gpu_policy.get("configured") else "尚未确认；执行 GPU 任务前必须确认"))
        table.add_row("运行目录", str(state.get("run_path")))
        console.clear()
        console.print(table)
        steps = pipeline.get("steps") or []
        if steps:
            step_table = Table(title="复现流程")
            step_table.add_column("序号", justify="right")
            step_table.add_column("阶段 ID")
            step_table.add_column("阶段说明")
            step_table.add_column("状态")
            for step in steps:
                step_table.add_row(str(step.get("index")), str(step.get("id")), str(step.get("name")), _zh_status(step.get("status")))
            console.print(step_table)
        runtime_tasks = (state.get("runtime") or {}).get("tasks") or []
        if runtime_tasks:
            rt_table = Table(title="执行任务队列")
            for label in ["任务 ID", "名称", "状态", "GPU", "进度", "ETA", "进度来源"]:
                rt_table.add_column(label)
            for item in runtime_tasks:
                prog = item.get("progress") or {}
                pct = prog.get("percent")
                progress_text = f"{float(pct):.1f}%" if isinstance(pct, (int, float)) else "未知"
                cur, total = prog.get("current"), prog.get("total")
                if total is not None:
                    progress_text += f" ({cur}/{total} {prog.get('unit','')})"
                gpu_text = ",".join(f"GPU{x}" for x in (item.get("gpu_ids") or [])) or ("CPU" if int((item.get("gpu_request") or {}).get("count", 1) or 0) == 0 else "待分配")
                rt_table.add_row(
                    str(item.get("task_id", "")), str(item.get("display_name", "")),
                    _zh_status(item.get("state")), gpu_text, progress_text,
                    _format_seconds(prog.get("eta_seconds")), str(prog.get("source", "unknown")),
                )
            console.print(rt_table)
        task = state.get("task") or {}
        if task.get("name") and not runtime_tasks:
            task_table = Table(title="当前任务")
            task_table.add_column("项目")
            task_table.add_column("当前值")
            task_progress = task.get("progress")
            if isinstance(task_progress, (int, float)):
                task_progress = f"{task_progress * 100:.1f}%"
            completed_value = task.get("completed")
            total_value = task.get("total")
            speed_value = task.get("speed")
            if task.get("unit") == "bytes":
                completed_total = f"{format_bytes(completed_value)} / {format_bytes(total_value)}"
                speed_value = f"{format_bytes(speed_value)}/秒" if speed_value is not None else "未知"
            else:
                completed_total = f"{completed_value} / {total_value} {task.get('unit', '')}"
            for key, value in [
                ("任务名称", task.get("name")),
                ("任务状态", _zh_status(task.get("status"))),
                ("任务进度", task_progress),
                ("已完成/总量", completed_total),
                ("处理速度", speed_value),
                ("预计剩余时间", _format_seconds(task.get("eta_seconds"))),
                ("任务消息", task.get("message", "")),
            ]:
                task_table.add_row(key, str(value))
            console.print(task_table)
        pending_items = state.get("pending_decisions") or []
        if pending_items:
            decision_table = Table(title="待确认决策")
            decision_table.add_column("ID")
            decision_table.add_column("等级")
            decision_table.add_column("阶段")
            decision_table.add_column("问题")
            decision_table.add_column("推荐")
            for item in pending_items:
                decision_table.add_row(
                    str(item.get("decision_id", "")),
                    f"L{item.get('level', '?')}",
                    str(item.get("stage", "")),
                    str(item.get("question", "")),
                    str(item.get("recommended_option") or item.get("default_option") or ""),
                )
            console.print(decision_table)
        runtime_gpu = ((state.get("runtime") or {}).get("gpu") or {}).get("gpus") or []
        gpus = runtime_gpu or state.get("last_gpu") or []
        if gpus:
            gpu_table = Table(title="GPU 状态与任务归属")
            columns = [
                ("index", "编号"), ("name", "型号"), ("util_gpu_pct", "利用率(%)"),
                ("memory_used_mb", "已用显存(MiB)"), ("memory_free_mb", "空闲显存(MiB)"),
                ("memory_total_mb", "总显存(MiB)"), ("temperature_c", "温度(℃)"),
                ("scheduler_state", "调度状态"), ("assigned_task_ids", "paper-repro 任务"),
            ]
            available_keys = [item for item in columns if item[0] in gpus[0]]
            for _, label in available_keys:
                gpu_table.add_column(label)
            for row in gpus:
                values = []
                for key, _ in available_keys:
                    value = row.get(key, "")
                    if key == "scheduler_state":
                        value = _zh_status(value)
                    if isinstance(value, list):
                        value = ",".join(str(x) for x in value)
                    values.append(str(value))
                gpu_table.add_row(*values)
            console.print(gpu_table)
        if not args.watch:
            break
        time.sleep(args.interval)
    return 0

def _runtime_paths(paths: WorkspacePaths, run: RunPaths | None = None) -> rte.RuntimePaths:
    run = run or current_run(paths)
    runtime = rte.RuntimePaths(run.root)
    runtime.ensure()
    return runtime


def _parse_gpu_ids(raw: str) -> list[int]:
    values: list[int] = []
    for item in str(raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            value = int(item)
        except ValueError as exc:
            raise ReproError(f"GPU ID 必须是整数：{item}") from exc
        if value < 0:
            raise ReproError("GPU ID 不能为负数")
        if value not in values:
            values.append(value)
    return values


def _runtime_workspace_defaults(paths: WorkspacePaths) -> dict[str, Any]:
    config = workspace_config(paths)
    runtime_cfg = config.get("runtime", {}) or {}
    return {
        "default_gpu_ids": [int(x) for x in runtime_cfg.get("default_gpu_ids", [])],
        "max_parallel_tasks": runtime_cfg.get("max_parallel_tasks"),
        "confirm_each_run": bool(runtime_cfg.get("confirm_each_run", True)),
    }


def cmd_gpu_prepare(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    runtime = _runtime_paths(paths, run)
    telemetry = rte.parse_nvidia_smi()
    policy = rte.load_gpu_policy(runtime)
    defaults = _runtime_workspace_defaults(paths)
    detected = [int(row["index"]) for row in telemetry if row.get("index") is not None]
    suggested = [x for x in defaults.get("default_gpu_ids", []) if x in detected] or detected
    payload = {
        "schema_version": 1,
        "run_id": run.root.name,
        "configured_for_run": bool(policy.get("configured")),
        "requires_confirmation": not bool(policy.get("configured")),
        "detected_gpus": telemetry,
        "workspace_default_gpu_ids": defaults.get("default_gpu_ids", []),
        "suggested_gpu_ids": suggested,
        "current_policy": policy,
        "question_zh": (
            "本次复现允许 paper-repro 调度哪些 GPU？请从检测到的 GPU 编号中选择；"
            "调度器只会使用你确认的 GPU，并默认避开检测到的外部繁忙 GPU。"
        ),
        "answer_examples": [
            ",".join(str(x) for x in suggested) if suggested else "none",
            str(suggested[0]) if suggested else "none",
            "none",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_gpu_inspect(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    runtime = _runtime_paths(paths, run)
    print(json.dumps(rte.gpu_snapshot(runtime), ensure_ascii=False, indent=2))
    return 0


def cmd_gpu_show(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    runtime = _runtime_paths(paths, run)
    print(json.dumps({
        "run_id": run.root.name,
        "policy": rte.load_gpu_policy(runtime),
        "workspace_defaults": _runtime_workspace_defaults(paths),
        "telemetry": rte.gpu_snapshot(runtime),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_gpu_configure(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    runtime = _runtime_paths(paths, run)
    telemetry = rte.parse_nvidia_smi()
    detected = {int(row["index"]) for row in telemetry if row.get("index") is not None}
    raw = args.ids
    if args.interactive:
        print("检测到 GPU：")
        if telemetry:
            for row in telemetry:
                print(
                    f"  GPU{row.get('index')}: {row.get('name')} · "
                    f"显存 {row.get('memory_used_mb')}/{row.get('memory_total_mb')} MiB · "
                    f"利用率 {row.get('util_gpu_pct')}%"
                )
        else:
            print("  未检测到 NVIDIA GPU")
        default_ids = _runtime_workspace_defaults(paths).get("default_gpu_ids", []) or sorted(detected)
        default_text = ",".join(str(x) for x in default_ids)
        raw = input(f"本次允许调度的 GPU ID（逗号分隔；none=只跑 CPU）[{default_text or 'none'}]: ").strip() or default_text
    if str(raw).strip().lower() in {"none", "cpu", "cpu-only"}:
        gpu_ids: list[int] = []
    else:
        gpu_ids = _parse_gpu_ids(raw)
    missing = [idx for idx in gpu_ids if idx not in detected]
    if missing and not args.allow_missing:
        raise ReproError(f"这些 GPU 当前不可见：{missing}；检测到：{sorted(detected)}")
    current = rte.load_gpu_policy(runtime)
    sched = dict(current.get("scheduler") or {})
    if args.max_parallel is not None:
        sched["max_parallel_tasks"] = int(args.max_parallel)
    elif gpu_ids:
        sched["max_parallel_tasks"] = min(max(1, int(sched.get("max_parallel_tasks", len(gpu_ids)))), len(gpu_ids))
    else:
        sched["max_parallel_tasks"] = max(1, int(args.cpu_parallel or 1))
    if args.external_busy_memory_mb is not None:
        sched["external_busy_memory_mb"] = int(args.external_busy_memory_mb)
    if args.external_busy_util_pct is not None:
        sched["external_busy_util_pct"] = int(args.external_busy_util_pct)
    sched["allow_external_busy"] = bool(args.allow_external_busy)
    policy = {
        **current,
        "allowed_gpu_ids": gpu_ids,
        "cpu_allowed": True,
        "selection_source": "user-confirmed",
        "scheduler": sched,
    }
    saved = rte.save_gpu_policy(runtime, policy)
    gpu_decision_id = "dec-gpu-" + uuid.uuid4().hex[:8]
    selection_id = "cpu-only" if not gpu_ids else "gpu-" + "-".join(str(x) for x in gpu_ids)
    append_jsonl(run.decisions, {
        "ts": now(), "action": "opened", "decision_id": gpu_decision_id,
        "title": "确认本次 GPU 调度资源池",
        "question": "本次复现允许 paper-repro 自动调度哪些物理 GPU？",
        "category": "gpu-resource-pool", "stage": "execution", "impact": "high",
        "reversibility": "reversible", "confidence": 1.0, "score": 0, "level": 2,
        "handling": "用户明确确认", "requires_user": False, "blocking": False,
        "options": [{"id": selection_id, "label": ("CPU only" if not gpu_ids else ",".join(f"GPU{x}" for x in gpu_ids)), "consequence": "调度器仅使用该资源池", "recommended": True}],
        "default_option": selection_id, "recommended_option": selection_id,
        "preference_key": "runtime.gpu_pool", "reasons": ["GPU 资源归属影响并行度、费用与服务器其他任务"],
        "status": "resolved", "selected_option": selection_id, "context": "run-level GPU pool confirmation",
        "user_involved": True,
    })
    render_decisions_markdown(run)
    if args.remember_workspace:
        config = workspace_config(paths)
        runtime_cfg = config.setdefault("runtime", {})
        runtime_cfg["default_gpu_ids"] = gpu_ids
        runtime_cfg["max_parallel_tasks"] = sched.get("max_parallel_tasks")
        runtime_cfg["confirm_each_run"] = True
        runtime_cfg["updated_at"] = now()
        save_workspace_config(paths, config)
    event(run, "gpu.pool.confirmed", gpu_ids=gpu_ids, remember_workspace=bool(args.remember_workspace))
    print(json.dumps({
        "configured": True,
        "run_id": run.root.name,
        "gpu_ids": gpu_ids,
        "scheduler": sched,
        "remembered_workspace": bool(args.remember_workspace),
        "note": "调度器只会使用这些 GPU；未被选择的 GPU 不属于本次复现资源池。",
    }, ensure_ascii=False, indent=2))
    return 0


def _parse_progress_adapter(raw: str) -> dict[str, Any]:
    if not raw:
        return {"type": "auto"}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReproError(f"Invalid progress adapter JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ReproError("progress adapter must be a JSON object")
    allowed = {"auto", "native", "tqdm", "jsonl-line-count", "line-count", "file-count", "regex-log"}
    kind = str(data.get("type", "auto"))
    if kind not in allowed:
        raise ReproError(f"Unsupported progress adapter: {kind}")
    data["type"] = kind
    return data


def _ensure_runtime_submission_allowed(paths: WorkspacePaths, run: RunPaths) -> dict[str, Any]:
    blocked = pending_decisions(run, blocking_only=True)
    if blocked:
        titles = "；".join(str(item.get("title", item.get("decision_id"))) for item in blocked[:5])
        raise DecisionPendingError(
            f"当前有 {len(blocked)} 项待确认决策，已阻止提交新任务：{titles}\n"
            "查看：paper-repro decisions checkpoint"
        )
    project_env = configured_execution_env(paths)
    if not project_env:
        raise DecisionPendingError(
            "项目 Conda 尚未配置，无法提交执行任务。先运行 paper-repro env create/use。"
        )
    sandbox = dict(execution_security_policy(paths).get("sandbox") or {})
    if str(sandbox.get("mode", "auto")) != "trusted-off" and not rte.sandbox_backend_status().get("available"):
        raise DecisionPendingError(
            "执行安全策略要求 OS 沙箱，但当前未检测到 bubblewrap/bwrap。"
            "安装 bwrap 后重试；若该仓库已人工审查且你愿意承担同用户权限风险，"
            "可显式执行 paper-repro security sandbox set --mode trusted-off --yes。"
        )
    return project_env


def _ensure_scheduler(paths: WorkspacePaths, run: RunPaths) -> dict[str, Any]:
    runtime = _runtime_paths(paths, run)
    return rte.start_scheduler_detached(runtime, str(Path(__file__).resolve()), str(paths.workspace))


def cmd_runtime_submit(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    project_env = _ensure_runtime_submission_allowed(paths, run)
    safe_command(args.command)
    runtime = _runtime_paths(paths, run)
    preferred = _parse_gpu_ids(args.gpu_ids)
    dependencies = [item.strip() for item in (args.depends_on or []) if item.strip()]
    sec_policy = execution_security_policy(paths)
    secret_env = _validate_task_secret_env(paths, args.secret_env or [])
    task = rte.add_task(
        runtime,
        display_name=args.name,
        stage=args.stage,
        command=args.command,
        workspace=str(paths.workspace),
        execution_env=project_env,
        timeout_seconds=args.timeout,
        estimate_seconds=args.estimate,
        gpu_count=args.gpu_count,
        gpu_ids=preferred,
        min_free_memory_mb=args.min_free_memory_mb,
        priority=args.priority,
        dependencies=dependencies,
        parallel_group_id=args.parallel_group or None,
        progress_adapter=_parse_progress_adapter(args.progress_adapter),
        output_paths=list(args.output or []),
        sandbox_policy=task_sandbox_policy(paths),
        secret_env=secret_env,
    )
    scheduler = _ensure_scheduler(paths, run) if args.start_scheduler else rte.scheduler_state(runtime)
    update_state(run, status="running", stage="execution", message=f"任务已进入持久队列：{args.name}")
    print(json.dumps({"task": task, "scheduler": scheduler}, ensure_ascii=False, indent=2))
    return 0


def _load_plan_input(args: argparse.Namespace, paths: WorkspacePaths) -> dict[str, Any]:
    if getattr(args, "file", ""):
        target = Path(args.file)
        if not target.is_absolute():
            target = paths.workspace / target
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ReproError(f"Cannot read execution plan {target}: {exc}") from exc
    else:
        raw = getattr(args, "tasks_json", "")
        if not raw:
            raise ReproError("Provide --file or --tasks-json")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReproError(f"Invalid --tasks-json: {exc}") from exc
        data = parsed if isinstance(parsed, dict) else {"tasks": parsed}
    if not isinstance(data, dict):
        raise ReproError("Execution plan must be a JSON object")
    data.setdefault("source", "opencode-agent")
    data.setdefault("workspace", str(paths.workspace))
    return data


def cmd_runtime_plan_save(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    runtime = _runtime_paths(paths, run)
    plan = _load_plan_input(args, paths)
    for item in plan.get("tasks", []):
        safe_command(str(item.get("command", "")))
    saved = rte.save_plan(runtime, plan)
    print(json.dumps({"plan_path": str(runtime.plan), "plan": saved}, ensure_ascii=False, indent=2))
    return 0


def cmd_runtime_plan_show(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    runtime = _runtime_paths(paths, run)
    plan = read_json(runtime.plan, {}) or {}
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


def cmd_runtime_plan_submit(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    project_env = _ensure_runtime_submission_allowed(paths, run)
    runtime = _runtime_paths(paths, run)
    if args.file or args.tasks_json:
        plan = _load_plan_input(args, paths)
        for item in plan.get("tasks", []):
            safe_command(str(item.get("command", "")))
        rte.save_plan(runtime, plan)
    else:
        plan = read_json(runtime.plan, {}) or {}
    if not plan:
        raise ReproError("No execution plan exists. Save a plan first.")
    for item in plan.get("tasks", []):
        safe_command(str(item.get("command", "")))
    existing = {t.get("task_id") for t in rte.read_tasks(runtime)}
    sec_policy = execution_security_policy(paths)
    pending_plan = dict(plan)
    pending_tasks = [dict(item) for item in plan.get("tasks", []) if item.get("task_id") not in existing]
    for item in pending_tasks:
        item["secret_env"] = _validate_task_secret_env(paths, item.get("secret_env") or [])
        item["sandbox"] = task_sandbox_policy(paths)
    pending_plan["sandbox"] = task_sandbox_policy(paths)
    pending_plan["tasks"] = pending_tasks
    created = rte.submit_plan(runtime, pending_plan, project_env, str(paths.workspace)) if pending_plan["tasks"] else []
    scheduler = _ensure_scheduler(paths, run)
    gpu_prepare = {
        "configured": bool(rte.load_gpu_policy(runtime).get("configured")),
        "command": "paper-repro gpu prepare --json",
    }
    update_state(run, status="running", stage="execution", message=f"执行计划已提交：新增 {len(created)} 个任务")
    print(json.dumps({
        "run_id": run.root.name,
        "submitted": len(created),
        "already_present": len(plan.get("tasks", [])) - len(created),
        "scheduler": scheduler,
        "gpu_pool": gpu_prepare,
        "tasks": created,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_runtime_status(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    runtime = _runtime_paths(paths, run)
    payload = rte.refresh_snapshot(runtime)
    payload["run_state"] = status_dict(paths, include_runtime=False)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_runtime_tasks(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    tasks = rte.read_tasks(_runtime_paths(paths, run))
    if args.active:
        tasks = [t for t in tasks if t.get("state") in rte.ACTIVE_STATES]
    if args.pending:
        tasks = [t for t in tasks if t.get("state") in rte.QUEUE_STATES]
    print(json.dumps(tasks, ensure_ascii=False, indent=2))
    return 0


def cmd_runtime_task(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    task = rte.task_by_id(_runtime_paths(paths, run), args.task_id)
    if not task:
        raise ReproError(f"Task not found: {args.task_id}")
    print(json.dumps(task, ensure_ascii=False, indent=2))
    return 0


def cmd_runtime_gpu(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    print(json.dumps(rte.gpu_snapshot(_runtime_paths(paths, run)), ensure_ascii=False, indent=2))
    return 0


def cmd_runtime_events(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    events = rte.read_events_after(_runtime_paths(paths, run), args.after or None, limit=args.limit)
    print(json.dumps(events, ensure_ascii=False, indent=2))
    return 0


def cmd_runtime_cancel(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    print(json.dumps(rte.cancel_task(_runtime_paths(paths, run), args.task_id), ensure_ascii=False, indent=2))
    return 0


def cmd_runtime_retry(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    runtime = _runtime_paths(paths, run)
    item = rte.retry_task(runtime, args.task_id)
    scheduler = _ensure_scheduler(paths, run)
    print(json.dumps({"task": item, "scheduler": scheduler}, ensure_ascii=False, indent=2))
    return 0


def cmd_scheduler_start(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    print(json.dumps(_ensure_scheduler(paths, run), ensure_ascii=False, indent=2))
    return 0


def cmd_scheduler_status(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    print(json.dumps(rte.scheduler_state(_runtime_paths(paths, run)), ensure_ascii=False, indent=2))
    return 0


def cmd_scheduler_stop(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    print(json.dumps(rte.stop_scheduler(_runtime_paths(paths, run)), ensure_ascii=False, indent=2))
    return 0


def cmd_scheduler_serve(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    return rte.scheduler_loop(_runtime_paths(paths, run), str(Path(__file__).resolve()), str(paths.workspace))


def cmd_scheduler_task_worker(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    return rte.task_worker(_runtime_paths(paths, run), args.task_id)


REMOTE_CONTRACT_VERSION = 1
REMOTE_CONTRACT_NAME = "paper-repro-remote"
REMOTE_CONTRACT_STATUS = "frozen"
REMOTE_CAPABILITIES = {
    "snapshot": 1,
    "events": 1,
    "decisions": 1,
    "task_registry": 1,
    "gpu_assignment": 1,
    "progress_adapters": 1,
    "discover": 1,
    "session_hint": 1,
    "command_audit": 1,
    # v2.1 compatibility alias. Consumers should prefer session_hint.
    "opencode_session_hint": 1,
}
REMOTE_COMMAND_STATES = {"queued", "dispatched", "accepted", "completed", "failed", "expired", "cancelled"}
REMOTE_COMMAND_TERMINAL_STATES = {"completed", "failed", "expired", "cancelled"}
REMOTE_COMMAND_TRANSITIONS = {
    "queued": {"queued", "dispatched", "accepted", "failed", "expired", "cancelled"},
    "dispatched": {"dispatched", "accepted", "failed", "expired", "cancelled"},
    "accepted": {"accepted", "completed", "failed", "cancelled"},
    "completed": {"completed"},
    "failed": {"failed"},
    "expired": {"expired"},
    "cancelled": {"cancelled"},
}

def _legacy_workspace_id(path: Path) -> str:
    """v2.1-compatible path-derived ID, used only for first migration."""
    return "ws-" + hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:12]


def _workspace_id(paths: WorkspacePaths, *, persist: bool = True) -> str:
    """Return the stable cross-system workspace ID.

    New workspaces get a random persistent ID. Existing v2.1 workspaces are migrated
    once from the old path-derived ID so an upgrade does not invalidate Bridge cursors.
    After it is persisted in .paper-repro/config.json, moving the workspace does not
    change the identity.
    """
    raw = read_json(paths.config, {}) or {}
    existing = str(raw.get("workspace_id") or "").strip()
    if re.fullmatch(r"ws-[0-9a-f]{12}", existing):
        return existing
    if paths.config.exists() or not persist:
        workspace_id = _legacy_workspace_id(paths.workspace)
    else:
        workspace_id = "ws-" + uuid.uuid4().hex[:12]
    if persist:
        data = workspace_config(paths)
        data["workspace_id"] = workspace_id
        save_workspace_config(paths, data)
    return workspace_id


_REMOTE_TIME_KEYS = {
    "generated_at", "started_at", "finished_at", "created_at", "updated_at",
    "resolved_at", "estimated_finish_at", "ts", "stopped_at", "enabled_at",
}


def _rfc3339(value: Any) -> Any:
    if not isinstance(value, str) or not value.strip():
        return value
    text = value.strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _remote_normalize_times(value: Any, key: str | None = None) -> Any:
    """Normalize all remote-contract timestamps to RFC3339 with an explicit offset."""
    if isinstance(value, dict):
        return {k: _remote_normalize_times(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_remote_normalize_times(v, key) for v in value]
    if key in _REMOTE_TIME_KEYS or (isinstance(key, str) and key.endswith("_at")):
        return _rfc3339(value)
    return value


def _remote_print(payload: dict[str, Any]) -> None:
    print(json.dumps(_remote_normalize_times(payload), ensure_ascii=False, indent=2))

def _remote_binding(run: RunPaths, workspace: Path) -> dict[str, Any]:
    data = read_json(run.opencode_binding, {}) or {}
    return {
        "session_id": data.get("session_id"),
        "directory": data.get("directory") or str(workspace.resolve()),
        "source": data.get("source") or "workspace-default",
        "updated_at": data.get("updated_at"),
        "hint_only": True,
    }

def _remote_decision_item(item: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "decision_id": item.get("decision_id"),
        "run_id": run_id,
        "task_id": item.get("task_id"),
        "level": item.get("level"),
        "stage": item.get("stage"),
        "category": item.get("category"),
        "impact": item.get("impact"),
        "reversibility": item.get("reversibility"),
        "title": item.get("title"),
        "question": item.get("question"),
        "options": [
            {
                "id": opt.get("id"),
                "label": opt.get("label"),
                "consequence": opt.get("consequence", ""),
                "recommended": bool(opt.get("recommended", False)),
            }
            for opt in item.get("options", [])
        ],
        "recommended_option": item.get("recommended_option") or item.get("default_option"),
        "allow_custom_answer": False,
        "allow_remember": int(item.get("level", 0) or 0) < 3 and bool(item.get("preference_key")),
        "blocking": bool(item.get("blocking", False)),
        "state": item.get("status", "pending"),
        "created_at": item.get("ts"),
        "resolved_at": item.get("resolved_at"),
        "selected_option": item.get("selected_option"),
    }

def cmd_remote_capabilities(args: argparse.Namespace) -> int:
    payload = {
        "schema_version": REMOTE_CONTRACT_VERSION,
        "contract": {
            "name": REMOTE_CONTRACT_NAME,
            "major": 1,
            "minor": 0,
            "status": REMOTE_CONTRACT_STATUS,
            "compatibility": "additive-with-capability-versioning",
        },
        "paper_repro_version": SYSTEM_VERSION,
        "generated_at": now(),
        "capabilities": dict(REMOTE_CAPABILITIES),
        "cursor_scope": "run",
        "id_scopes": {
            "workspace_id": "persistent-workspace",
            "run_id": "workspace",
            "task_id": "run-unique-never-reused",
            "event_id": "run-monotonic",
            "decision_id": "run",
            "request_id": "run",
            "idempotency_key": "run-command-audit",
        },
        "truth_confidence_levels": ["high", "medium", "low", "unknown"],
        "time_format": "RFC3339-with-offset",
        "consumer_rules": {
            "ignore_unknown_fields": True,
            "field_semantics_are_stable_within_capability_major": True,
            "capability_version_changes_before_semantic_breaks": True,
        },
        "deprecations": [
            {
                "name": "capabilities.opencode_session_hint",
                "replacement": "capabilities.session_hint",
                "remove_before_contract_major": 2,
            },
            {
                "name": "snapshot.task_list / snapshot.gpu",
                "replacement": "snapshot.tasks / snapshot.gpu_assignments",
                "remove_before_contract_major": 2,
            },
        ],
        "remote_write_policy": {
            "research_decision_by_id_only": True,
            "arbitrary_shell": False,
            "opencode_http_proxy": False,
            "l3_policy_bypass": False,
            "writes_are_audited": True,
        },
    }
    _remote_print(payload)
    return 0

def _remote_safe_task(task: dict[str, Any], include_command: bool = False) -> dict[str, Any]:
    data = dict(task)
    metadata = dict(data.get("metadata") or {})
    data.setdefault("kind", metadata.get("kind") or "experiment")
    data.setdefault("launcher", metadata.get("launcher"))
    data.setdefault("worker_pids", list(metadata.get("worker_pids") or []))
    data["startup_estimate_seconds"] = data.get("estimate_seconds")
    progress = dict(data.get("progress") or {})
    confidence = str(progress.get("eta_confidence") or progress.get("confidence") or "unknown")
    if confidence not in {"high", "medium", "low", "unknown"}:
        confidence = "unknown"
    progress["confidence"] = confidence
    progress.setdefault("eta_source", progress.get("eta_source"))
    progress.setdefault("source", "unknown")
    progress.setdefault("updated_at", data.get("updated_at"))
    data["progress"] = progress
    if not include_command:
        data.pop("command", None)
        data.pop("cwd", None)
        data.pop("metadata", None)
        env = dict(data.get("project_env") or {})
        if env:
            env.pop("prefix", None)
            data["project_env"] = env
    return data


def cmd_remote_discover(args: argparse.Namespace) -> int:
    """List registered workspaces/runs without requiring the caller to know a project path."""
    rows: list[dict[str, Any]] = []
    registry = load_registry().get("workspaces", {})
    for workspace, info in registry.items():
        state_home = Path(str(info.get("state_home", ""))).expanduser()
        run_root = Path(str(info.get("last_run", ""))).expanduser()
        if not state_home.exists() or not run_root.exists():
            continue
        state = read_json(run_root / "meta" / "state.json", {}) or {}
        runtime_snapshot = read_json(run_root / "runtime" / "snapshot.json", {}) or {}
        queue = runtime_snapshot.get("queue") or {}
        scheduler = runtime_snapshot.get("scheduler") or {}
        active = int(queue.get("active", 0) or 0)
        queued = int(queue.get("queued", 0) or 0)
        status = str(state.get("status", "unknown"))
        if args.active and not (active or queued or status in {"running", "waiting-decision", "awaiting-decision", "waiting-resources", "waiting-gpu-confirmation"}):
            continue
        rows.append({
            "workspace": workspace,
            "workspace_id": str(info.get("workspace_id") or _workspace_id(WorkspacePaths(Path(workspace).resolve(), state_home), persist=False)),
            "run_id": run_root.name,
            "run_root": str(run_root),
            "snapshot_path": str(run_root / "runtime" / "snapshot.json"),
            "status": status,
            "stage": state.get("stage"),
            "message": state.get("message"),
            "active_tasks": active,
            "queued_tasks": queued,
            "scheduler_state": scheduler.get("state"),
            "scheduler_alive": bool(scheduler.get("alive")),
            "updated_at": info.get("updated_at"),
        })
    rows.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    payload = {"schema_version": REMOTE_CONTRACT_VERSION, "generated_at": now(), "cursor_scope": "run", "workspaces": rows}
    _remote_print(payload)
    return 0


def cmd_remote_snapshot(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    runtime = _runtime_paths(paths, run)
    base = status_dict(paths, include_runtime=False)
    rt = rte.refresh_snapshot(runtime)
    task_list = [_remote_safe_task(item, args.include_command) for item in rt.get("tasks", [])]
    active = [item for item in task_list if item.get("state") in rte.ACTIVE_STATES]
    queued = [item for item in task_list if item.get("state") in rte.QUEUE_STATES]
    recent = sorted(
        [item for item in task_list if item.get("state") in rte.TERMINAL_STATES],
        key=lambda item: str(item.get("finished_at") or item.get("updated_at") or ""),
        reverse=True,
    )[:20]
    pending = pending_decisions(run)
    blocker_count = len([x for x in folded_issues(issue_records(run.blockers), id_field="blocker_id") if x.get("status") == "open"])
    gpu = rt.get("gpu") or {}
    assignments: dict[str, Any] = {}
    for gpu_id, task_ids in (gpu.get("assignments") or {}).items():
        ids = [str(x) for x in (task_ids or [])]
        assignments[str(gpu_id)] = {
            "task_id": ids[0] if len(ids) == 1 else None,
            "task_ids": ids,
            "role": "current-reproduction",
            "assignment_source": "paper-repro",
            "confidence": "high" if len(ids) <= 1 else "low",
            "integrity": "ok" if len(ids) <= 1 else "conflict",
            "updated_at": rt.get("generated_at") or now(),
        }
    pipeline = dict(base.get("pipeline") or {})
    stage_index = pipeline.get("current_step")
    stage_total = pipeline.get("total_steps")
    completed_stages = pipeline.get("completed_steps")
    pipeline_payload = {
        "current_stage": base.get("stage"),
        "stage_index": stage_index,
        "stage_total": stage_total,
        "completed_stages": completed_stages,
        "remaining_stages": pipeline.get("remaining_steps"),
        "percent": round((float(completed_stages or 0) / max(1.0, float(stage_total or 1))) * 100, 3),
        "steps": pipeline.get("steps", []),
    }
    payload = {
        "schema_version": REMOTE_CONTRACT_VERSION,
        "generated_at": now(),
        "workspace": str(paths.workspace),
        "workspace_id": _workspace_id(paths),
        "run": {
            "run_id": base.get("run_id"),
            "state": base.get("status"),
            "started_at": base.get("started_at"),
            "elapsed_seconds": base.get("elapsed_seconds"),
            "message": base.get("message"),
        },
        "pipeline": pipeline_payload,
        "scheduler": rt.get("scheduler") or {},
        "queue": rt.get("queue") or {},
        "tasks": {
            "active": active,
            "queued": queued,
            "recent_completed": recent,
        },
        "gpu_assignments": assignments,
        "decisions": {
            "pending_count": len(pending),
            "blocking_count": len([x for x in pending if x.get("blocking")]),
        },
        "blockers": {"active_count": blocker_count},
        "system_issues": {"active_count": int(base.get("system_issue_count", 0) or 0)},
        "opencode": _remote_binding(run, paths.workspace),
        "privacy": "full" if args.include_command else "safe",
        "contract": {
            "name": REMOTE_CONTRACT_NAME,
            "major": 1,
            "minor": 0,
            "status": REMOTE_CONTRACT_STATUS,
            "capabilities": "paper-repro remote capabilities --json",
            "event_cursor_scope": "run",
        },
        # Compatibility aliases for early v2.0 clients. New Bridge code should use the fields above.
        "task_list": task_list,
        "gpu": {
            "policy": gpu.get("policy") or {},
            "assignments": gpu.get("assignments") or {},
        },
    }
    if args.include_telemetry:
        payload["gpu_telemetry"] = gpu.get("gpus") or []
    _remote_print(payload)
    return 0


def cmd_remote_events(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    runtime = _runtime_paths(paths, run)
    page = rte.read_events_page(runtime, args.after or None, limit=args.limit)
    payload = {
        "schema_version": REMOTE_CONTRACT_VERSION,
        "workspace_id": _workspace_id(paths),
        "run_id": run.root.name,
        "cursor_scope": "run",
        **page,
    }
    _remote_print(payload)
    return 0


def cmd_remote_decisions(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    items = pending_decisions(run)
    payload = {
        "schema_version": REMOTE_CONTRACT_VERSION,
        "workspace_id": _workspace_id(paths),
        "run_id": run.root.name,
        "decisions": [_remote_decision_item(item, run.root.name) for item in items],
    }
    _remote_print(payload)
    return 0


def cmd_remote_decide(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    runtime = _runtime_paths(paths, run)
    workspace_id = _workspace_id(paths)
    resolution_record = None
    with rte.runtime_lock(runtime):
        items = {item.get("decision_id"): item for item in folded_decisions(decision_records(run.decisions))}
        item = items.get(args.decision_id)
        if not item:
            _remote_print({
                "ok": False, "code": "decision_not_found", "decision_id": args.decision_id,
                "workspace_id": workspace_id, "run_id": run.root.name, "state": "not_found",
            })
            return 2
        if item.get("status") != "pending":
            selected = item.get("selected_option")
            same = selected == args.option
            _remote_print({
                "ok": bool(same),
                "code": "already_resolved",
                "decision_id": args.decision_id,
                "workspace_id": workspace_id,
                "run_id": run.root.name,
                "resolved_option": selected,
                "requested_option": args.option,
                # v2.1 aliases retained for Contract v1 compatibility.
                "selected": selected,
                "requested": args.option,
                "state": "already_resolved",
                "resolved_at": item.get("resolved_at"),
                "conflict": not same,
            })
            return 0 if same else 4
        option_ids = {option.get("id") for option in item.get("options", [])}
        if args.option not in option_ids:
            _remote_print({
                "ok": False, "code": "invalid_option", "decision_id": args.decision_id,
                "workspace_id": workspace_id, "run_id": run.root.name, "state": "invalid_option",
                "requested_option": args.option, "allowed_options": sorted(str(x) for x in option_ids),
            })
            return 2
        resolution_record = {
            "ts": now(), "action": "resolved", "decision_id": args.decision_id, "status": "resolved",
            "selected_option": args.option, "resolution_note": args.note, "remember_scope": args.remember,
            "user_involved": True, "resolution_source": "remote-bridge",
        }
        append_jsonl(run.decisions, resolution_record)
    preference_key = item.get("preference_key")
    if args.remember != "none" and preference_key and int(item.get("level", 0) or 0) < 3:
        save_decision_preference(paths, str(preference_key), args.option, args.remember)
    remaining = pending_decisions(run, blocking_only=True)
    update_state(
        run,
        status="awaiting-decision" if remaining else "running",
        message=(f"仍有 {len(remaining)} 项决策待确认" if remaining else "决策已确认，可以继续执行"),
        pending_decision_count=len(remaining),
    )
    atomic_json(run.decision_checkpoint, {"generated_at": now(), "stage": item.get("stage", ""), "pending": remaining})
    render_decisions_markdown(run)
    event(run, "decision.resolved", decision_id=args.decision_id, selected_option=args.option, remember=args.remember, source="remote-bridge")
    rte.emit_event(runtime, "decision.resolved", data={
        "decision_id": args.decision_id, "selected_option": args.option, "remember": args.remember, "source": "remote-bridge",
    })
    _remote_print({
        "ok": True, "code": "resolved", "decision_id": args.decision_id,
        "workspace_id": workspace_id, "run_id": run.root.name,
        "selected_option": args.option, "resolved_option": args.option, "selected": args.option,
        "state": "resolved", "resolved_at": resolution_record.get("ts") if resolution_record else now(),
        "remaining_pending": len(remaining),
    })
    return 0

def cmd_remote_session_show(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    _remote_print({
        "schema_version": REMOTE_CONTRACT_VERSION,
        "workspace_id": _workspace_id(paths),
        "run_id": run.root.name,
        "opencode": _remote_binding(run, paths.workspace),
    })
    return 0


def cmd_remote_session_bind(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    directory = str(Path(args.directory or paths.workspace).expanduser().resolve())
    payload = {
        "schema_version": REMOTE_CONTRACT_VERSION,
        "session_id": args.session_id or None,
        "directory": directory,
        "source": args.source or "remote-bridge",
        "updated_at": now(),
        "hint_only": True,
    }
    atomic_json(run.opencode_binding, payload)
    try:
        os.chmod(run.opencode_binding, 0o600)
    except OSError:
        pass
    rte.emit_event(_runtime_paths(paths, run), "opencode.binding_updated", data={
        "session_id": payload.get("session_id"), "directory": directory, "source": payload.get("source"),
    })
    _remote_print({"ok": True, "workspace_id": _workspace_id(paths), "run_id": run.root.name, "opencode": payload})
    return 0


def cmd_remote_session_clear(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    run.opencode_binding.unlink(missing_ok=True)
    rte.emit_event(_runtime_paths(paths, run), "opencode.binding_cleared", data={})
    _remote_print({"ok": True, "workspace_id": _workspace_id(paths), "run_id": run.root.name, "state": "cleared"})
    return 0


def _fold_remote_commands(path: Path) -> list[dict[str, Any]]:
    folded: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        req = str(rec.get("request_id") or "")
        if not req:
            continue
        current = folded.setdefault(req, {})
        current.update(rec)
    return sorted(folded.values(), key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""), reverse=True)

def cmd_remote_command_record(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    runtime = _runtime_paths(paths, run)
    workspace_id = _workspace_id(paths)
    with rte.runtime_lock(runtime):
        folded = _fold_remote_commands(run.remote_commands)
        existing = {x.get("request_id"): x for x in folded}
        prior = existing.get(args.request_id)
        if args.idempotency_key:
            for rec in folded:
                if rec.get("idempotency_key") == args.idempotency_key and rec.get("request_id") != args.request_id:
                    _remote_print({
                        "ok": False, "code": "idempotency_conflict", "request_id": args.request_id,
                        "existing_request_id": rec.get("request_id"), "state": "idempotency_conflict",
                        "workspace_id": workspace_id, "run_id": run.root.name,
                    })
                    return 4
        if prior and args.idempotency_key and prior.get("idempotency_key") not in {None, "", args.idempotency_key}:
            _remote_print({
                "ok": False, "code": "idempotency_conflict", "request_id": args.request_id,
                "state": "idempotency_conflict", "workspace_id": workspace_id, "run_id": run.root.name,
            })
            return 4
        if prior and (prior.get("target") != args.target or prior.get("type") != args.command_type):
            _remote_print({
                "ok": False, "code": "request_identity_conflict", "request_id": args.request_id,
                "state": "request_identity_conflict", "workspace_id": workspace_id, "run_id": run.root.name,
            })
            return 4
        prior_state = str(prior.get("state") or "") if prior else ""
        if prior_state and args.state not in REMOTE_COMMAND_TRANSITIONS.get(prior_state, {prior_state}):
            _remote_print({
                "ok": False, "code": "invalid_state_transition", "request_id": args.request_id,
                "previous_state": prior_state, "requested_state": args.state,
                "state": "invalid_state_transition", "workspace_id": workspace_id, "run_id": run.root.name,
            })
            return 4
        record = {
            "schema_version": REMOTE_CONTRACT_VERSION,
            "request_id": args.request_id,
            "workspace_id": workspace_id,
            "run_id": run.root.name,
            "target": args.target,
            "type": args.command_type,
            "session_id": args.session_id or None,
            "state": args.state,
            "requires_idle": bool(args.requires_idle),
            "priority": args.priority,
            "ttl_seconds": args.ttl_seconds,
            "idempotency_key": args.idempotency_key or None,
            "summary": redact(args.summary or ""),
            "payload_sha256": args.payload_sha256 or None,
            "created_at": prior.get("created_at") if prior else now(),
            "updated_at": now(),
            "source": "remote-bridge",
        }
        append_jsonl(run.remote_commands, record)
    try:
        os.chmod(run.remote_commands, 0o600)
    except OSError:
        pass
    rte.emit_event(runtime, f"remote.command.{args.state}", data={
        "request_id": args.request_id, "target": args.target, "type": args.command_type,
        "session_id": args.session_id or None, "idempotency_key": args.idempotency_key or None,
    })
    _remote_print({"ok": True, "code": "recorded", **record})
    return 0

def cmd_remote_command_list(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    workspace_id = _workspace_id(paths)
    items = _fold_remote_commands(run.remote_commands)
    for item in items:
        item.setdefault("schema_version", REMOTE_CONTRACT_VERSION)
        item.setdefault("workspace_id", workspace_id)
        item.setdefault("run_id", run.root.name)
    if args.state:
        items = [x for x in items if x.get("state") == args.state]
    _remote_print({
        "schema_version": REMOTE_CONTRACT_VERSION, "workspace_id": workspace_id,
        "run_id": run.root.name, "commands": items[:args.limit],
    })
    return 0

def cmd_stage(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    state = read_json(run.state, {}) or {}
    pipeline = state.get("pipeline") or pipeline_state()
    if args.step_total is not None and args.step_total > 0 and args.step_total != len(pipeline.get("steps", [])):
        existing = {int(step.get("index", 0)): step for step in pipeline.get("steps", [])}
        pipeline["steps"] = [
            existing.get(index, {"index": index, "id": f"step-{index}", "name": f"Step {index}", "status": "pending"})
            for index in range(1, args.step_total + 1)
        ]
    if args.step is not None:
        found = False
        for step in pipeline.get("steps", []):
            if int(step.get("index", 0)) == args.step:
                found = True
                step["id"] = args.stage
                if args.step_name:
                    step["name"] = args.step_name
                step["status"] = args.step_status or ("completed" if args.status == "completed" else "running")
            elif int(step.get("index", 0)) < args.step and step.get("status") == "pending":
                step["status"] = "completed"
        if not found:
            pipeline.setdefault("steps", []).append({
                "index": args.step,
                "id": args.stage,
                "name": args.step_name or args.stage,
                "status": args.step_status or "running",
            })
            pipeline["steps"] = sorted(pipeline["steps"], key=lambda item: int(item.get("index", 0)))
    pipeline = recalculate_pipeline(pipeline)
    task_fraction = float((state.get("task") or {}).get("progress") or 0.0)
    reset_task = args.step is not None and args.progress is None
    if reset_task:
        task_fraction = 0.0
    changes: dict[str, Any] = {
        "stage": args.stage,
        "status": args.status,
        "message": args.message,
        "pipeline": pipeline,
        "progress": progress_from_pipeline({"pipeline": pipeline}, task_fraction),
    }
    if reset_task:
        changes["task"] = {
            "name": "",
            "status": "idle",
            "progress": 0.0,
            "completed": 0,
            "total": None,
            "unit": "",
            "speed": None,
            "eta_seconds": None,
        }
    if args.progress is not None:
        task = dict(state.get("task") or {})
        task["progress"] = max(0.0, min(1.0, args.progress))
        changes["task"] = task
        changes["progress"] = progress_from_pipeline({"pipeline": pipeline}, args.progress)
    if args.eta is not None:
        changes["eta_seconds"] = args.eta
    update_state(run, **changes)
    event(run, "stage.updated", **changes)
    rte.emit_event(_runtime_paths(paths, run), "run.stage_changed", data={
        "stage": args.stage, "status": args.status, "step": args.step, "step_total": args.step_total,
    })
    if args.status == "completed" and int((pipeline or {}).get("completed_steps", 0) or 0) >= int((pipeline or {}).get("total_steps", 8) or 8):
        rte.emit_event(_runtime_paths(paths, run), "run.completed", data={"stage": args.stage})
    elif args.status == "failed":
        rte.emit_event(_runtime_paths(paths, run), "run.failed", data={"stage": args.stage, "message": args.message})
    print(json.dumps(status_dict(paths), ensure_ascii=False, indent=2))
    return 0


def cmd_env_show(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    ensure_workspace_layout(paths)
    result = {
        "workspace": str(paths.workspace),
        "control_env": active_conda_info(),
        "project_env": configured_execution_env(paths),
        "config": workspace_config(paths),
        "note": "control_env runs OpenCode/paper-repro; project_env runs project commands",
    }
    print(environment_banner(paths))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def select_conda_environment(name: str | None, prefix: str | None) -> dict[str, Any]:
    environments = conda_environments()
    candidate: dict[str, str] | None = None
    if prefix:
        target = str(Path(prefix).expanduser().resolve())
        candidate = next((item for item in environments if item["prefix"] == target), None)
        if candidate is None and Path(target).exists() and (Path(target) / "conda-meta").exists():
            candidate = {"name": Path(target).name, "prefix": target}
    elif name:
        matches = [item for item in environments if item["name"] == name or Path(item["prefix"]).name == name]
        if len(matches) > 1:
            raise ReproError(f"More than one Conda environment matches {name}; use --prefix")
        candidate = matches[0] if matches else None
    if candidate is None:
        raise ReproError(f"Conda environment not found: {prefix or name}")
    if candidate["name"] == "base" or Path(candidate["prefix"]).name in {"anaconda3", "miniconda3", "miniforge3"}:
        raise ReproError("Project execution environment cannot be Conda base")
    python_path = Path(candidate["prefix"]) / "bin/python"
    if not python_path.exists():
        raise ReproError(f"Python is missing from Conda environment: {python_path}")
    version = capture([str(python_path), "--version"])
    return {
        "type": "conda",
        "name": candidate["name"],
        "prefix": candidate["prefix"],
        "python": str(python_path),
        "python_version": version,
        "configured_at": now(),
        "role": "project",
        "configured": True,
    }


def cmd_env_use(args: argparse.Namespace) -> int:
    active_conda()
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    ensure_workspace_layout(paths)
    selected = select_conda_environment(args.name, args.prefix)
    config = workspace_config(paths)
    config["execution_env"] = selected
    config["enforce_execution_env"] = not args.no_enforce
    save_workspace_config(paths, config)
    try:
        run = current_run(paths)
        update_state(run, execution_env=selected, message=f"已选择项目 Conda：{selected['name']}")
        event(run, "environment.selected", execution_env=selected)
    except ReproError:
        pass
    print(environment_banner(paths))
    print(json.dumps({"workspace": str(paths.workspace), "project_env": selected}, ensure_ascii=False, indent=2))
    return 0


def cmd_env_create(args: argparse.Namespace) -> int:
    active_conda()
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    if not args.name and not args.prefix:
        raise ReproError("Specify --name or --prefix for the new project environment")
    if args.name == "base":
        raise ReproError("Refusing to create or use Conda base")
    command = [conda_executable(), "create", "-y"]
    if args.prefix:
        command += ["-p", str(Path(args.prefix).expanduser().resolve())]
    else:
        command += ["-n", args.name]
    command += [f"python={args.python}"]
    command += list(args.package or [])
    print(environment_banner(paths))
    print("Creating project Conda environment:", shlex.join(command), flush=True)
    result = subprocess.run(command, cwd=paths.workspace)
    if result.returncode != 0:
        raise ReproError(f"conda create failed with exit code {result.returncode}")
    selected = select_conda_environment(args.name, args.prefix)
    config = workspace_config(paths)
    config["execution_env"] = selected
    config["enforce_execution_env"] = True
    save_workspace_config(paths, config)
    print(environment_banner(paths))
    print(json.dumps({"created": selected, "workspace": str(paths.workspace)}, ensure_ascii=False, indent=2))
    return 0


def cmd_env_clear(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    config = workspace_config(paths)
    config["execution_env"] = None
    save_workspace_config(paths, config)
    print(json.dumps({
        "workspace": str(paths.workspace),
        "project_env": None,
        "warning": "Project commands are blocked until another non-base Conda environment is configured.",
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_security_show(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    policy = execution_security_policy(paths)
    payload = {
        "workspace": str(paths.workspace),
        "policy": policy,
        "sandbox_backend": rte.sandbox_backend_status(),
        "allowed_download_roots_effective": [str(x) for x in allowed_download_roots(paths)],
        "note": "auto/required sandbox modes fail closed when bwrap is unavailable; trusted-off is an explicit trusted-repository escape hatch.",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_security_sandbox_set(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    if args.mode == "trusted-off" and not args.yes:
        raise ReproError("trusted-off disables OS-level project sandboxing; repeat with --yes only for a repository you trust")
    config = workspace_config(paths)
    security = config.setdefault("execution_security", {})
    security["sandbox"] = {"mode": args.mode, "backend": "auto", "network": args.network}
    save_workspace_config(paths, config)
    print(json.dumps({"sandbox": security["sandbox"], "backend_status": rte.sandbox_backend_status()}, ensure_ascii=False, indent=2))
    return 0


def cmd_security_secret_allow(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ReproError("Task secret access is sensitive; repeat with --yes after reviewing the target repository")
    if not SECRET_NAME_RE.fullmatch(args.name):
        raise ReproError(f"Invalid secret env name: {args.name}")
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    config = workspace_config(paths)
    security = config.setdefault("execution_security", {})
    names = sorted(set(str(x) for x in security.get("allowed_secret_env", [])) | {args.name})
    security["allowed_secret_env"] = names
    save_workspace_config(paths, config)
    print(json.dumps({"allowed_secret_env": names}, ensure_ascii=False, indent=2))
    return 0


def cmd_security_secret_revoke(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    config = workspace_config(paths)
    security = config.setdefault("execution_security", {})
    names = [str(x) for x in security.get("allowed_secret_env", []) if str(x) != args.name]
    security["allowed_secret_env"] = names
    save_workspace_config(paths, config)
    print(json.dumps({"allowed_secret_env": names}, ensure_ascii=False, indent=2))
    return 0


def cmd_security_download_root_add(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ReproError("External download roots expand the project write boundary; repeat with --yes")
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    root = Path(args.path).expanduser().resolve()
    home = Path.home().resolve()
    sensitive_candidates = [
        home,
        Path(os.environ.get("PAPER_REPRO_CONFIG_HOME", str(home / ".config" / "paper-repro"))).expanduser().resolve(),
        Path(os.environ.get("PAPER_REPRO_CONFIG_FILE", str(home / ".config" / "paper-repro" / "config.json"))).expanduser().resolve(),
        home / ".ssh", home / ".aws", home / ".config" / "gcloud",
    ]
    if str(root) == "/" or root == home or any(_path_within(candidate, root) for candidate in sensitive_candidates):
        raise ReproError("Refusing overly broad/sensitive download root; choose a dedicated data/model directory")
    config = workspace_config(paths)
    security = config.setdefault("execution_security", {})
    roots = sorted(set(str(x) for x in security.get("allowed_download_roots", [])) | {str(root)})
    security["allowed_download_roots"] = roots
    save_workspace_config(paths, config)
    print(json.dumps({"allowed_download_roots": roots}, ensure_ascii=False, indent=2))
    return 0


def cmd_security_download_root_remove(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    root = str(Path(args.path).expanduser().resolve())
    config = workspace_config(paths)
    security = config.setdefault("execution_security", {})
    roots = [str(x) for x in security.get("allowed_download_roots", []) if str(x) != root]
    security["allowed_download_roots"] = roots
    save_workspace_config(paths, config)
    print(json.dumps({"allowed_download_roots": roots}, ensure_ascii=False, indent=2))
    return 0


def _repair_private_tree(root: Path) -> dict[str, int]:
    counts = {"directories": 0, "files": 0, "symlinks_skipped": 0}
    if not root.exists():
        return counts
    if root.is_symlink():
        raise ReproError(f"Refusing to repair permissions through symlink root: {root}")
    root.chmod(0o700)
    counts["directories"] += 1
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        safe_dirs = []
        for name in dirs:
            target = current_path / name
            if target.is_symlink():
                counts["symlinks_skipped"] += 1
                continue
            target.chmod(0o700)
            counts["directories"] += 1
            safe_dirs.append(name)
        dirs[:] = safe_dirs
        for name in files:
            target = current_path / name
            if target.is_symlink():
                counts["symlinks_skipped"] += 1
                continue
            target.chmod(0o600)
            counts["files"] += 1
    return counts


def cmd_security_permissions_repair(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ReproError("Permission repair changes state/config modes to private 700/600; repeat with --yes")
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    payload: dict[str, Any] = {"scope": args.scope, "workspace": str(paths.workspace), "repaired": {}}
    if args.scope in {"workspace", "all"}:
        payload["repaired"]["workspace_state"] = {
            "path": str(paths.state_home),
            **_repair_private_tree(paths.state_home),
        }
    if args.scope in {"global", "all"}:
        global_root = PAPER_REPRO_CONFIG_HOME.resolve()
        payload["repaired"]["global_config"] = {
            "path": str(global_root),
            **_repair_private_tree(global_root),
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    try:
        import requests
    except ImportError as exc:
        raise ReproError("requests is required for paper-repro download") from exc

    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    active_conda()
    run = current_run(paths)
    ensure_run_layout(run)
    output = Path(args.output).expanduser()
    if not output.is_absolute():
        output = (paths.workspace / output).resolve()
    else:
        output = output.resolve()
    roots = allowed_download_roots(paths)
    if not any(_path_within(output, root) for root in roots):
        raise ReproError(
            f"下载输出越过允许目录：{output}. 允许目录：{[str(x) for x in roots]}. "
            "如确有需要，先由用户执行 paper-repro security download-root add /path --yes"
        )
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    existing = output.stat().st_size if output.exists() and args.resume else 0
    headers = {"User-Agent": f"paper-repro/{SYSTEM_VERSION}"}
    if existing:
        headers["Range"] = f"bytes={existing}-"

    command_id = datetime.now().strftime("%H%M%S") + "-" + uuid.uuid4().hex[:6]
    log_path = run.logs / f"{command_id}-download.log"
    started = time.time()
    print(environment_banner(paths, run), flush=True)
    print(f"DOWNLOAD       : {args.url}\nOUTPUT         : {output}\n", flush=True)

    state_before = read_json(run.state, {}) or {}
    task = {
        "name": args.stage,
        "status": "running",
        "progress": 0.0,
        "completed": existing,
        "total": None,
        "unit": "bytes",
        "speed": None,
        "eta_seconds": None,
        "message": output.name,
        "started_at": now(),
    }
    update_state(
        run,
        status="running",
        stage=args.stage,
        message=f"正在下载 {output.name}",
        task=task,
        execution_env=configured_execution_env(paths),
        control_env=active_conda_info(),
        progress=progress_from_pipeline(state_before, 0.0),
    )
    start_record = {
        "record_type": "start",
        "id": command_id,
        "stage": args.stage,
        "command": f"download {redact(args.url)} -> {output}",
        "cwd": str(paths.workspace),
        "started_at": now(),
        "status": "running",
        "log": str(log_path.relative_to(run.root)),
    }
    append_jsonl(run.commands, start_record)
    event(run, "download.started", url=redact(args.url), output=str(output), existing_bytes=existing)

    try:
        with requests.get(args.url, stream=True, headers=headers, timeout=(30, args.read_timeout), allow_redirects=True) as response:
            response.raise_for_status()
            append_mode = existing > 0 and response.status_code == 206
            if existing and not append_mode:
                existing = 0
            content_length = response.headers.get("Content-Length")
            remaining = int(content_length) if content_length and content_length.isdigit() else None
            total = existing + remaining if remaining is not None else None
            mode = "ab" if append_mode else "wb"
            completed = existing
            last_update = started
            last_reported = completed
            last_console = 0.0
            with output.open(mode) as target, log_path.open("w", encoding="utf-8") as log:
                log.write(
                    f"# paper-repro download log\n# run_id={run.root.name}\n# url={redact(args.url)}\n"
                    f"# output={output}\n# resumed_from={existing}\n# started_at={now()}\n\n"
                )
                for chunk in response.iter_content(chunk_size=max(64 * 1024, args.chunk_size)):
                    if not chunk:
                        continue
                    target.write(chunk)
                    completed += len(chunk)
                    current_time = time.time()
                    elapsed = max(0.001, current_time - started)
                    speed = (completed - existing) / elapsed
                    fraction = completed / total if total else 0.0
                    eta = int((total - completed) / speed) if total and speed > 0 else None
                    if current_time - last_update >= 0.5:
                        task.update({
                            "progress": min(1.0, fraction) if total else 0.0,
                            "completed": completed,
                            "total": total,
                            "speed": speed,
                            "eta_seconds": eta,
                            "message": output.name,
                        })
                        state_now = read_json(run.state, {}) or {}
                        update_state(
                            run,
                            task=task,
                            progress=progress_from_pipeline(state_now, fraction if total else 0.0),
                            eta_seconds=eta,
                            message=f"正在下载 {output.name}：{format_bytes(completed)} / {format_bytes(total)}",
                        )
                        log.write(
                            f"{now()} completed={completed} total={total} speed_bps={speed:.1f} eta_seconds={eta}\n"
                        )
                        log.flush()
                        last_update = current_time
                        if sys.stdout.isatty() or current_time - last_console >= 5:
                            percent = f"{fraction * 100:6.2f}%" if total else "   ?  %"
                            line = (
                                f"\r{percent}  {format_bytes(completed)} / {format_bytes(total)}  "
                                f"{format_bytes(speed)}/s  ETA {eta if eta is not None else '?'}s"
                            )
                            print(line, end="", flush=True)
                            last_console = current_time
                    last_reported = completed
            if sys.stdout.isatty():
                print()

        digest = sha256_file(output)
        if args.sha256 and digest.lower() != args.sha256.lower():
            raise ReproError(f"SHA256 mismatch for {output}: expected {args.sha256}, got {digest}")
        elapsed = int(time.time() - started)
        final_task = dict(task)
        final_task.update({
            "status": "succeeded",
            "progress": 1.0,
            "completed": output.stat().st_size,
            "total": output.stat().st_size,
            "eta_seconds": 0,
            "finished_at": now(),
        })
        final_state = read_json(run.state, {}) or {}
        update_state(
            run,
            status="succeeded",
            message=f"下载完成：{output.name}",
            task=final_task,
            eta_seconds=0,
            progress=max(float(final_state.get("progress", 0.0)), progress_from_pipeline(final_state, 1.0)),
        )
        artifact = {
            "registered_at": now(),
            "run_id": run.root.name,
            "kind": args.kind,
            "path": str(output),
            "size_bytes": output.stat().st_size,
            "sha256": digest,
            "source": redact(args.url),
            "revision": "",
        }
        append_jsonl(run.artifacts, artifact)
        finish_record = {
            "record_type": "finish",
            "id": command_id,
            "stage": args.stage,
            "status": "succeeded",
            "exit_code": 0,
            "elapsed_seconds": elapsed,
            "log": str(log_path.relative_to(run.root)),
        }
        append_jsonl(run.commands, finish_record)
        event(run, "download.finished", **artifact, elapsed_seconds=elapsed)
        print(json.dumps({"status": "succeeded", "artifact": artifact, "elapsed_seconds": elapsed}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        elapsed = int(time.time() - started)
        failed_state = read_json(run.state, {}) or {}
        failed_task = dict(failed_state.get("task") or task)
        failed_task.update({"status": "failed", "eta_seconds": None, "finished_at": now()})
        update_state(run, status="failed", message=f"下载失败：{exc}", task=failed_task, eta_seconds=None)
        append_jsonl(run.commands, {
            "record_type": "finish",
            "id": command_id,
            "stage": args.stage,
            "status": "failed",
            "exit_code": 1,
            "elapsed_seconds": elapsed,
            "log": str(log_path.relative_to(run.root)),
        })
        record_issue(
            paths,
            run,
            title="下载任务失败",
            details=str(exc),
            severity="error",
            component="downloader",
            stage=args.stage,
            command=f"download {args.url}",
            log=str(log_path),
            scope="project",
        )
        raise


def doctor_checks(paths: WorkspacePaths) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, value: Any, recommendation: str = "") -> None:
        checks.append({"name": name, "ok": ok, "value": value, "recommendation": recommendation})

    prefix = os.environ.get("CONDA_PREFIX", "")
    env_name = os.environ.get("CONDA_DEFAULT_ENV", "")
    add("conda_active", bool(prefix) and env_name != "base", env_name or "inactive", "Activate a dedicated non-base Conda environment")
    add("control_conda_prefix", bool(prefix), prefix or "inactive", "OpenCode and paper-repro should run from a dedicated control Conda environment")
    add("python_in_conda", bool(prefix) and Path(sys.executable).resolve().is_relative_to(Path(prefix).resolve()), sys.executable, "Re-run bootstrap in the active Conda environment")
    node = shutil.which("node") or ""
    add("node_in_conda", bool(prefix) and node and Path(node).resolve().is_relative_to(Path(prefix).resolve()), node or "missing", "Run bash bootstrap.sh to install Node.js inside Conda")
    opencode = shutil.which("opencode") or ""
    add("opencode_available", bool(opencode), opencode or "missing", "Run bash bootstrap.sh")
    cli = shutil.which("paper-repro") or ""
    add("paper_repro_cli", bool(cli), cli or "missing", "Run bash bootstrap.sh")
    gh = shutil.which("gh") or ""
    add("github_cli", bool(gh), gh or "missing", "Run a full bootstrap to install GitHub CLI in the control Conda")
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "opencode"
    add("global_reproduce_command", (config_home / "commands/reproduce.md").exists(), str(config_home / "commands/reproduce.md"), "Run PAPER_REPRO_GLOBAL_INSTALL=1 bash bootstrap.sh")
    try:
        project_env = configured_execution_env(paths, fallback_active=False)
        if project_env:
            project_prefix = Path(project_env["prefix"]).resolve()
            project_python = project_prefix / "bin/python"
            add("project_conda_configured", True, f"{project_env.get('name')} · {project_prefix}")
            add("project_python_available", project_python.exists(), str(project_python), "Repair or select the project Conda environment")
            add("project_conda_not_base", project_env.get("name") != "base", project_env.get("name"), "Use a dedicated non-base project environment")
        else:
            add(
                "project_conda_configured",
                False,
                "not configured; project runtime commands are blocked",
                "Use: paper-repro env create --name <ENV> --python <VERSION>, or env use --name <ENV>",
            )
    except Exception as exc:
        add("project_conda_configured", False, str(exc), "Use paper-repro env use to select a valid environment")
    secrets_permissions = oct(SECRETS_FILE.stat().st_mode & 0o777) if SECRETS_FILE.exists() else "not created"
    add("persistent_secrets_file", True, str(SECRETS_FILE), "Use paper-repro secrets init/set to persist API and MCP tokens")
    add("persistent_secrets_permissions", not SECRETS_FILE.exists() or (SECRETS_FILE.stat().st_mode & 0o077) == 0, secrets_permissions, "Run chmod 600 on the secrets file")
    sec_policy = execution_security_policy(paths)
    sandbox_policy = dict(sec_policy.get("sandbox") or {})
    sandbox_status = rte.sandbox_backend_status()
    sandbox_ok = str(sandbox_policy.get("mode", "auto")) == "trusted-off" or bool(sandbox_status.get("available"))
    add("execution_sandbox", sandbox_ok, {"policy": sandbox_policy, "backend": sandbox_status}, "Install bubblewrap/bwrap, or explicitly use trusted-off only for reviewed repositories")
    add("task_secret_default_deny", len(sec_policy.get("allowed_secret_env", [])) == 0, list(sec_policy.get("allowed_secret_env", [])), "Keep task secret allowlist empty unless a specific experiment requires a credential")
    add("workspace_writable", os.access(paths.workspace, os.W_OK), str(paths.workspace), "Choose a writable project directory")
    add("git_workspace", git_root(paths.workspace) is not None, str(git_root(paths.workspace) or "not a Git repository"), "Launch OpenCode in the target repository root")
    add("nvidia_smi", shutil.which("nvidia-smi") is not None, shutil.which("nvidia-smi") or "missing", "GPU runs require a host NVIDIA driver")
    disk = shutil.disk_usage(paths.workspace)
    add("disk_free_gb", disk.free >= 10 * 1024**3, round(disk.free / 1024**3, 2), "Keep at least 10 GB free; large models may need much more")
    current = resolve_run_marker(paths)
    add("current_run", current is not None, str(current or "none"), "Use /reproduce or paper-repro init before status --watch")
    policy = decision_policy(paths)
    add("decision_policy", policy.get("mode") in DECISION_MODES, policy.get("mode"), "Use paper-repro decisions policy set --mode balanced")
    if current:
        try:
            pending_count = len(pending_decisions(RunPaths(current)))
            add("pending_decisions", pending_count == 0, pending_count, "Use paper-repro decisions checkpoint and resolve pending choices")
        except Exception as exc:
            add("pending_decisions", False, str(exc), "Inspect meta/decisions.jsonl")
    legacy = paths.workspace / ".repro"
    add("legacy_state_absent", not legacy.exists(), str(legacy) if legacy.exists() else "none", "Run paper-repro migrate-legacy if old state must be preserved")
    return checks


def create_doctor_report(paths: WorkspacePaths) -> dict[str, Any]:
    ensure_workspace_layout(paths)
    checks = doctor_checks(paths)
    report = {
        "schema_version": 1,
        "system_version": SYSTEM_VERSION,
        "created_at": now(),
        "workspace": str(paths.workspace),
        "state_home": str(paths.state_home),
        "checks": checks,
        "passed": all(check["ok"] for check in checks),
    }
    diagnostic_dir = paths.system / "diagnostics"
    diagnostic_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(diagnostic_dir / f"doctor-{local_stamp()}.json", report)
    atomic_json(diagnostic_dir / "latest.json", report)
    return report


def cmd_doctor(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    report = create_doctor_report(paths)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if args.strict and not report["passed"] else 0


def cmd_issue_add(args: argparse.Namespace) -> int:
    """Record a system-function problem or optimization opportunity."""
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    ensure_workspace_layout(paths)
    try:
        run = current_run(paths)
    except ReproError:
        run = None
    record = record_system_issue(
        paths,
        run,
        title=args.title,
        details=args.details,
        severity=args.severity,
        component=args.component,
        category=args.category,
        stage=args.stage,
        command=args.command,
        log=args.log,
        expected=args.expected,
        optimization=args.optimization,
    )
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


def cmd_issue_list(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    records = folded_issues(issue_records(paths.system / "issues.jsonl"), id_field="issue_id")
    if not args.all:
        records = [record for record in records if record.get("status") == "open"]
    print(json.dumps(records, ensure_ascii=False, indent=2))
    return 0


def cmd_issue_resolve(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    resolution = {
        "action": "resolved",
        "scope": "system",
        "issue_id": args.issue_id,
        "ts": now(),
        "status": "resolved",
        "resolution": args.resolution,
        "system_version": SYSTEM_VERSION,
    }
    append_jsonl(paths.system / "issues.jsonl", resolution)
    append_jsonl(GLOBAL_ISSUES, {**resolution, "workspace": str(paths.workspace)})
    render_issue_markdown(
        paths.system / "SYSTEM_ISSUES.md",
        "系统功能与优化问题汇总",
        issue_records(paths.system / "issues.jsonl"),
        kind="system",
    )
    print(json.dumps(resolution, ensure_ascii=False, indent=2))
    return 0


def cmd_blocker_add(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    record = record_blocker(
        paths,
        run,
        title=args.title,
        details=args.details,
        severity=args.severity,
        component=args.component,
        stage=args.stage,
        command=args.command,
        log=args.log,
    )
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


def cmd_blocker_list(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    records = folded_issues(issue_records(run.blockers), id_field="blocker_id")
    if not args.all:
        records = [record for record in records if record.get("status") == "open"]
    print(json.dumps(records, ensure_ascii=False, indent=2))
    return 0


def cmd_blocker_resolve(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = current_run(paths)
    resolution = {
        "action": "resolved",
        "scope": "project",
        "blocker_id": args.blocker_id,
        "ts": now(),
        "status": "resolved",
        "resolution": args.resolution,
        "system_version": SYSTEM_VERSION,
    }
    append_jsonl(run.blockers, resolution)
    render_issue_markdown(run.report / "RUN_BLOCKERS.md", "本次论文复现阻塞项", issue_records(run.blockers), kind="blocker")
    rte.emit_event(_runtime_paths(paths, run), "blocker.resolved", data={
        "blocker_id": args.blocker_id, "resolution": redact(args.resolution or ""),
    })
    print(json.dumps(resolution, ensure_ascii=False, indent=2))
    return 0

def cmd_runs_list(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    items = []
    if paths.runs.exists():
        current = resolve_run_marker(paths)
        for path in sorted((item for item in paths.runs.iterdir() if item.is_dir()), reverse=True):
            state = read_json(RunPaths(path).state, {})
            items.append({
                "run_id": path.name,
                "current": bool(current and current.resolve() == path.resolve()),
                "status": state.get("status", "unknown"),
                "stage": state.get("stage", ""),
                "updated_at": state.get("updated_at", ""),
                "path": str(path),
            })
    print(json.dumps(items, ensure_ascii=False, indent=2))
    return 0


def cmd_runs_use(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    run = paths.runs / args.run_id
    if not run.is_dir():
        raise ReproError(f"Unknown run: {run}")
    set_current(paths, run)
    register_workspace(paths, run)
    print(json.dumps({"current_run": args.run_id, "workspace": str(paths.workspace)}, ensure_ascii=False, indent=2))
    return 0


def cmd_paths(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    result = {
        "system_home": str(SYSTEM_HOME),
        "system_version": SYSTEM_VERSION,
        "workspace": str(paths.workspace),
        "state_home": str(paths.state_home),
        "runs": str(paths.runs),
        "current": str(resolve_run_marker(paths) or ""),
        "cache": str(paths.cache),
        "workspace_config": str(paths.config),
        "control_env": active_conda_info(),
        "project_env": configured_execution_env(paths),
        "system_issues": str(paths.system / "SYSTEM_ISSUES.md"),
        "global_registry": str(REGISTRY_FILE),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_feedback(args: argparse.Namespace) -> int:
    """Create a sanitized bundle focused on system functionality, not project implementation."""
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    ensure_workspace_layout(paths)
    create_doctor_report(paths)
    try:
        run = current_run(paths)
    except ReproError:
        run = None
    output = Path(args.output).expanduser().resolve() if args.output else paths.system / "feedback" / f"paper-repro-system-feedback-{local_stamp()}.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "created_at": now(),
        "system_version": SYSTEM_VERSION,
        "scope": "system-functionality",
        "workspace_included": bool(args.include_workspace_metadata),
        "run_metadata_included": bool(args.include_run_metadata and run),
        "logs_included": bool(args.include_logs and run),
        "redaction": "Known credential patterns are redacted; review the bundle before sharing.",
        "note": "Project-specific dependency, dataset and experiment failures are excluded by default.",
        "self_improvement_summary_included": True,
    }
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("feedback_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        candidates = [
            paths.system / "SYSTEM_ISSUES.md",
            paths.system / "issues.jsonl",
            paths.system / "diagnostics/latest.json",
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                content = redact(candidate.read_text(encoding="utf-8", errors="replace"))
                archive.writestr(str(candidate.relative_to(paths.state_home)), content)
        improvement_summary = []
        for item in folded_improvements():
            improvement_summary.append({
                "improvement_id": item.get("improvement_id"),
                "source": item.get("source"),
                "source_issue_id": item.get("source_issue_id"),
                "title": redact(str(item.get("title", ""))),
                "status": item.get("status"),
                "risk": item.get("risk", ""),
                "system_version": item.get("system_version", ""),
                "created_at": item.get("created_at", ""),
            })
        archive.writestr("system/self-improvement-summary.json", json.dumps(improvement_summary, ensure_ascii=False, indent=2))
        if args.include_run_metadata:
            event_file = paths.system / "opencode-events.jsonl"
            if event_file.exists():
                text = event_file.read_text(encoding="utf-8", errors="replace")[-512 * 1024:]
                archive.writestr("system/opencode-events-tail.jsonl", redact(text))
        if args.include_workspace_metadata:
            archive.writestr("workspace_metadata.json", json.dumps({
                "workspace_name": paths.workspace.name,
                "state_home": ".paper-repro",
                "control_env": active_conda_info(),
                "execution_env_configured": bool(configured_execution_env(paths)),
            }, ensure_ascii=False, indent=2))
        if run and args.include_run_metadata:
            for candidate in [run.state, run.manifest]:
                if candidate.exists():
                    archive.writestr(f"run-metadata/{candidate.name}", redact(candidate.read_text(encoding="utf-8", errors="replace")))
        if run and args.include_logs and run.logs.exists():
            for log in sorted(run.logs.glob("*.log"))[-args.max_logs:]:
                text = log.read_text(encoding="utf-8", errors="replace")[-args.max_log_kb * 1024:]
                archive.writestr(f"system-log-samples/{log.name}", redact(text))
    print(json.dumps({"feedback_bundle": str(output), **manifest}, ensure_ascii=False, indent=2))
    return 0

def cmd_disable(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    paths.enabled.unlink(missing_ok=True)
    print(json.dumps({"disabled": True, "workspace": str(paths.workspace)}, ensure_ascii=False))
    return 0


def copy_tree_contents(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def cmd_migrate_legacy(args: argparse.Namespace) -> int:
    paths = discover_workspace(args.workspace, args.state_root, args.latest)
    legacy = paths.workspace / ".repro"
    if not legacy.exists():
        raise ReproError(f"No legacy state found: {legacy}")
    ensure_workspace_layout(paths)
    backup = paths.system / f"legacy-backup-{local_stamp()}"
    shutil.copytree(legacy, backup)
    old_runs = paths.workspace / "runs"
    if old_runs.exists():
        for old_run in old_runs.iterdir():
            if old_run.is_dir():
                destination = paths.runs / old_run.name
                if not destination.exists():
                    shutil.copytree(old_run, destination)
    old_current = legacy / "current"
    if old_current.is_symlink():
        old_target = old_current.resolve()
        candidate = paths.runs / old_target.name
        if candidate.exists():
            set_current(paths, candidate)
            register_workspace(paths, candidate)
    record_issue(
        paths,
        None,
        title="已迁移旧版运行状态",
        details=f"Legacy state copied from {legacy} to {paths.state_home}; backup: {backup}",
        severity="info",
        component="migration",
    )
    print(json.dumps({"migrated": True, "legacy": str(legacy), "backup": str(backup), "state_home": str(paths.state_home)}, ensure_ascii=False, indent=2))
    return 0


def add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", help="Target project/workspace. Defaults to nearest .paper-repro ancestor or Git root.")
    parser.add_argument("--state-root", help="Override state directory. Defaults to <workspace>/.paper-repro")
    parser.add_argument("--latest", action="store_true", help="Fallback to the most recently registered workspace")




# ---------------------------------------------------------------------------
# Guarded self-improvement
# ---------------------------------------------------------------------------

SELF_IMPROVE_MODES = {
    "off": "关闭",
    "manual": "仅手动",
    "propose-only": "只生成修复提案",
    "guarded": "受控自动迭代",
}

SELF_IMPROVE_EXCLUDED_CATEGORIES = {
    "project", "project-blocker", "credentials", "license-access",
    "external-service", "network-transient", "self-improvement",
}

SELF_IMPROVE_SAFE_PREFIXES = (
    "docs/", "tests/", ".opencode/agents/", ".opencode/commands/", "schemas/",
)
SELF_IMPROVE_SAFE_FILES = {
    "README.md", "AGENTS.md", "CHANGELOG_CN.md", "USAGE_CN.md",
}
SELF_IMPROVE_PROTECTED_PREFIXES = (
    "scripts/", ".opencode/tools/", ".opencode/plugins/", "configs/",
)
SELF_IMPROVE_PROTECTED_FILES = {
    "bootstrap.sh", "opencode.jsonc", "scripts/uninstall.sh", ".gitignore",
}
SELF_IMPROVE_RISK_PATTERNS = [
    re.compile(r"\b(sudo|apt-get|yum|dnf|pacman|mkfs|dd\s+if=)\b", re.I),
    re.compile(r"rm\s+-rf", re.I),
    re.compile(r"git\s+push", re.I),
    re.compile(r"permission[^\n]{0,80}(allow|deny|ask)", re.I),
    re.compile(r"(api[_-]?key|token|password|secret)[^\n]{0,80}[=:]", re.I),
    re.compile(r"subprocess\.(run|Popen)|os\.system|shell\s*=\s*True", re.I),
    re.compile(r"mcp[^\n]{0,80}(write|create|delete|merge|push)", re.I),
]


def default_self_improvement_policy() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "enabled": True,
        "mode": "guarded",
        "auto_enqueue_system_issues": True,
        "auto_apply_safe_patches": True,
        "max_attempts": 2,
        "max_changed_files": 12,
        "auto_apply_max_files": 3,
        "require_smoke_tests": True,
        "resolve_issue_after_real_verification": True,
        "excluded_categories": sorted(SELF_IMPROVE_EXCLUDED_CATEGORIES),
    }


def self_improvement_policy() -> dict[str, Any]:
    policy = merge_dict(default_self_improvement_policy(), load_unified_config().get("self_improvement", {}) or {})
    mode = str(policy.get("mode", "guarded"))
    if mode not in SELF_IMPROVE_MODES:
        mode = "guarded"
    policy["mode"] = mode
    policy["enabled"] = bool(policy.get("enabled", True)) and mode != "off"
    return policy


def save_self_improvement_policy(data: dict[str, Any]) -> None:
    config = load_unified_config()
    data["updated_at"] = now()
    config["self_improvement"] = data
    save_unified_config(config)


def system_source_home() -> Path:
    configured = os.environ.get("PAPER_REPRO_SOURCE_HOME", "").strip()
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend([SYSTEM_HOME / "source", SYSTEM_HOME])
    for candidate in candidates:
        if (candidate / "bootstrap.sh").exists() and (candidate / "scripts/reproctl.py").exists():
            return candidate.resolve()
    raise ReproError(
        "未找到可迭代的 paper-repro 源码快照。请用 v0.9.0 或更高版本重新执行 bootstrap.sh。"
    )


def improvement_records() -> list[dict[str, Any]]:
    return issue_records(IMPROVE_QUEUE)


def folded_improvements(records: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    folded: dict[str, dict[str, Any]] = {}
    for record in records if records is not None else improvement_records():
        improvement_id = record.get("improvement_id")
        if not improvement_id:
            continue
        if record.get("action", "opened") == "opened":
            folded[improvement_id] = dict(record)
            folded[improvement_id]["status"] = record.get("status", "queued")
        elif improvement_id in folded:
            folded[improvement_id].update({k: v for k, v in record.items() if k not in {"action"}})
    return sorted(folded.values(), key=lambda item: item.get("created_at", item.get("ts", "")), reverse=True)


def get_improvement(improvement_id: str) -> dict[str, Any]:
    for item in folded_improvements():
        if item.get("improvement_id") == improvement_id:
            return item
    raise ReproError(f"未找到自我迭代任务：{improvement_id}")


def update_improvement(improvement_id: str, **fields: Any) -> dict[str, Any]:
    record = {"action": "updated", "improvement_id": improvement_id, "ts": now(), **fields}
    append_jsonl(IMPROVE_QUEUE, record)
    append_jsonl(IMPROVE_HISTORY, record)
    return get_improvement(improvement_id)


def _improvement_fingerprint(title: str, details: str, source_issue_id: str = "") -> str:
    normalized = "\n".join([source_issue_id.strip(), title.strip().lower(), details.strip().lower()])
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def _find_system_issue(issue_id: str) -> dict[str, Any] | None:
    for item in folded_issues(issue_records(GLOBAL_ISSUES), id_field="issue_id"):
        if item.get("issue_id") == issue_id:
            return item
    return None


def submit_improvement_candidate(
    *, title: str, details: str, source: str = "user-request", source_issue_id: str = "",
    workspace: str = "", run_id: str = "", priority: str = "normal",
) -> dict[str, Any]:
    policy = self_improvement_policy()
    if not policy.get("enabled"):
        raise ReproError("自我迭代功能已关闭")
    fingerprint = _improvement_fingerprint(title, details, source_issue_id)
    for existing in folded_improvements():
        if existing.get("fingerprint") == fingerprint and existing.get("status") not in {"discarded", "verified", "rolled-back"}:
            return existing
    improvement_id = f"IMP-{local_stamp()}-{uuid.uuid4().hex[:6]}"
    record = {
        "action": "opened",
        "improvement_id": improvement_id,
        "created_at": now(),
        "updated_at": now(),
        "system_version": SYSTEM_VERSION,
        "source": source,
        "source_issue_id": source_issue_id,
        "title": redact(title),
        "details": redact(details),
        "priority": priority,
        "workspace": workspace,
        "run_id": run_id,
        "fingerprint": fingerprint,
        "status": "queued",
        "attempts": 0,
    }
    append_jsonl(IMPROVE_QUEUE, record)
    append_jsonl(IMPROVE_HISTORY, record)
    return record


def enqueue_system_issue_candidate(record: dict[str, Any]) -> str:
    policy = self_improvement_policy()
    if not policy.get("enabled") or not policy.get("auto_enqueue_system_issues"):
        return ""
    category = str(record.get("category", ""))
    excluded = set(policy.get("excluded_categories", [])) | SELF_IMPROVE_EXCLUDED_CATEGORIES
    command = str(record.get("command", ""))
    if category in excluded or " improve " in f" {command} " or str(record.get("component")) == "self-improvement":
        return ""
    item = submit_improvement_candidate(
        title=str(record.get("title", "系统功能问题")),
        details="\n\n".join(filter(None, [
            str(record.get("details", "")),
            f"期望：{record.get('expected')}" if record.get("expected") else "",
            f"优化建议：{record.get('optimization')}" if record.get("optimization") else "",
        ])),
        source="system-issue",
        source_issue_id=str(record.get("issue_id", "")),
        workspace=str(record.get("workspace", "")),
        run_id=str(record.get("run_id", "")),
        priority="high" if record.get("severity") in {"critical", "error"} else "normal",
    )
    return str(item.get("improvement_id", ""))


def improvement_session(improvement_id: str) -> Path:
    return IMPROVE_SESSIONS / improvement_id


def improvement_source(improvement_id: str) -> Path:
    return improvement_session(improvement_id) / "source"


def _safe_improvement_path(improvement_id: str, relative: str) -> Path:
    root = improvement_source(improvement_id).resolve()
    if not root.exists():
        raise ReproError("迭代工作区尚未准备，请先执行 improve prepare")
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or ".git" in rel.parts:
        raise ReproError("只允许访问迭代工作区内的相对路径，且禁止访问 .git")
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ReproError("路径越过迭代工作区边界") from exc
    return target


def _run_capture(command: list[str], cwd: Path, timeout: int = 300, env: dict[str, str] | None = None) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
        return {
            "command": command,
            "exit_code": proc.returncode,
            "stdout": redact(proc.stdout[-20000:]),
            "stderr": redact(proc.stderr[-20000:]),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "passed": proc.returncode == 0,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "exit_code": 124,
            "stdout": redact((exc.stdout or "")[-20000:] if isinstance(exc.stdout, str) else ""),
            "stderr": "测试超时",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "passed": False,
        }


def _git(root: Path, *args: str, timeout: int = 120) -> dict[str, Any]:
    return _run_capture(["git", *args], root, timeout=timeout)


def _prepare_improvement(improvement_id: str, force: bool = False) -> dict[str, Any]:
    item = get_improvement(improvement_id)
    session = improvement_session(improvement_id)
    source = session / "source"
    if source.exists() and not force:
        return {"improvement_id": improvement_id, "session": str(session), "source": str(source), "status": item.get("status")}
    if session.exists() and force:
        shutil.rmtree(session)
    session.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        system_source_home(), source,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "dist", ".paper-repro", "runs", "*.zip"),
    )
    if not shutil.which("git"):
        raise ReproError("自我迭代需要 git 用于隔离差异和回滚")
    checks = [
        _git(source, "init", "-q"),
        _git(source, "config", "user.email", "paper-repro@localhost"),
        _git(source, "config", "user.name", "paper-repro self-improvement"),
        _git(source, "add", "-A"),
        _git(source, "commit", "-q", "-m", f"baseline {SYSTEM_VERSION}"),
    ]
    if any(not check["passed"] for check in checks):
        raise ReproError("无法初始化自我迭代 Git 基线：" + "\n".join(check["stderr"] for check in checks if not check["passed"]))
    context = {
        "improvement": item,
        "system_version": SYSTEM_VERSION,
        "source_snapshot": str(system_source_home()),
        "session": str(session),
        "source": str(source),
        "policy": self_improvement_policy(),
        "constraints": {
            "project_blockers_excluded": True,
            "no_direct_installed_source_edits": True,
            "max_attempts": self_improvement_policy().get("max_attempts", 2),
            "tests_required": True,
        },
    }
    atomic_json(session / "context.json", context)
    (session / "PROMPT.md").write_text(
        "# paper-repro 自我迭代任务\n\n"
        f"- ID：`{improvement_id}`\n"
        f"- 标题：{item.get('title')}\n"
        f"- 来源：{item.get('source')}\n"
        f"- 系统 Issue：`{item.get('source_issue_id') or '无'}`\n\n"
        "## 问题描述\n\n"
        f"{item.get('details')}\n\n"
        "## 约束\n\n"
        "1. 只修改本隔离源码副本，不直接修改目标论文项目或已安装系统。\n"
        "2. 项目依赖、数据和训练失败不是系统自改依据。\n"
        "3. 优先最小修复；不得降低安全、权限、Conda 隔离或审计能力。\n"
        "4. 修改后必须运行内建测试；失败最多修复两轮。\n"
        "5. 先生成差异和风险报告，再由策略决定自动应用或请求用户确认。\n",
        encoding="utf-8",
    )
    update_improvement(improvement_id, status="prepared", session=str(session), source_path=str(source))
    return {"improvement_id": improvement_id, "session": str(session), "source": str(source), "status": "prepared"}


def _changed_files(improvement_id: str) -> list[str]:
    root = improvement_source(improvement_id)
    _git(root, "add", "-N", ".")
    result = _git(root, "diff", "--name-only", "HEAD")
    if not result["passed"]:
        raise ReproError(result["stderr"] or "无法读取 Git 差异")
    return [line.strip() for line in result["stdout"].splitlines() if line.strip()]


def _improvement_diff(improvement_id: str) -> dict[str, Any]:
    root = improvement_source(improvement_id)
    _git(root, "add", "-N", ".")
    stat = _git(root, "diff", "--stat", "HEAD")
    diff = _git(root, "diff", "--no-ext-diff", "--unified=3", "HEAD", timeout=180)
    if not diff["passed"]:
        raise ReproError(diff["stderr"] or "无法生成差异")
    patch = improvement_session(improvement_id) / "changes.patch"
    patch.write_text(diff["stdout"], encoding="utf-8")
    return {"files": _changed_files(improvement_id), "stat": stat["stdout"], "patch": str(patch), "diff": diff["stdout"]}


def _classify_improvement(improvement_id: str) -> dict[str, Any]:
    data = _improvement_diff(improvement_id)
    files = data["files"]
    diff = data["diff"]
    reasons: list[str] = []
    protected = []
    for filename in files:
        if filename in SELF_IMPROVE_PROTECTED_FILES or filename.startswith(SELF_IMPROVE_PROTECTED_PREFIXES):
            protected.append(filename)
    if protected:
        reasons.append("修改了控制器、安装器、工具、插件或配置等受保护路径")
    risky_patterns = [pattern.pattern for pattern in SELF_IMPROVE_RISK_PATTERNS if pattern.search(diff)]
    if risky_patterns:
        reasons.append("差异触及权限、凭据、命令执行、外部写入或危险命令模式")
    policy = self_improvement_policy()
    if len(files) > int(policy.get("max_changed_files", 12)):
        reasons.append("修改文件数量超过自我迭代上限")
    safe_paths = all(filename in SELF_IMPROVE_SAFE_FILES or filename.startswith(SELF_IMPROVE_SAFE_PREFIXES) for filename in files)
    if not files:
        risk = "none"
    elif protected or risky_patterns or len(files) > int(policy.get("max_changed_files", 12)):
        risk = "high"
    elif safe_paths and len(files) <= int(policy.get("auto_apply_max_files", 3)):
        risk = "low"
    else:
        risk = "medium"
    return {
        "risk": risk,
        "files": files,
        "protected_files": protected,
        "risky_patterns": risky_patterns,
        "reasons": reasons,
        "auto_apply_eligible": risk == "low" and bool(policy.get("auto_apply_safe_patches", True)),
        "stat": data["stat"],
        "patch": data["patch"],
    }


def _scan_secret_leaks(source: Path) -> list[str]:
    secrets = load_unified_config().get("secrets", {}) or {}
    values = [(name, value) for name, value in secrets.items() if isinstance(value, str) and len(value) >= 8]
    if not values:
        return []
    findings: list[str] = []
    for file in source.rglob("*"):
        if not file.is_file() or ".git" in file.parts or file.stat().st_size > 2_000_000:
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, value in values:
            if value in text:
                findings.append(f"{file.relative_to(source)} 包含统一配置中的真实密钥 {name}")
    return findings


def _test_improvement(improvement_id: str) -> dict[str, Any]:
    source = improvement_source(improvement_id)
    if not source.exists():
        raise ReproError("请先 prepare 自我迭代任务")
    tests: list[dict[str, Any]] = []
    compile_targets = ["scripts/security.py", "scripts/runtime_engine.py", "scripts/reproctl.py"]
    existing_compile_targets = [item for item in compile_targets if (source / item).exists()]
    tests.append(_run_capture([sys.executable, "-m", "py_compile", *existing_compile_targets], source, 120))
    for script in ["bootstrap.sh", "scripts/uninstall.sh", "tests/smoke_test.sh"]:
        if (source / script).exists():
            tests.append(_run_capture(["bash", "-n", script], source, 60))
    json_errors = []
    for file in list((source / "schemas").glob("*.json")) + list((source / "configs").glob("*.json")):
        try:
            json.loads(file.read_text(encoding="utf-8"))
        except Exception as exc:
            json_errors.append(f"{file.relative_to(source)}: {exc}")
    tests.append({
        "command": ["json-validation"], "exit_code": 0 if not json_errors else 1,
        "stdout": "\n".join(json_errors), "stderr": "", "elapsed_seconds": 0,
        "passed": not json_errors,
    })
    secret_findings = _scan_secret_leaks(source)
    tests.append({
        "command": ["secret-leak-scan"], "exit_code": 0 if not secret_findings else 1,
        "stdout": "\n".join(secret_findings), "stderr": "", "elapsed_seconds": 0,
        "passed": not secret_findings,
    })
    policy = self_improvement_policy()
    # Remote Contract v1 is a frozen cross-repository compatibility boundary.
    # Any self-iteration that touches remote/runtime behavior must pass these gates
    # before the broader smoke suite is allowed to approve a patch.
    for contract_test in ["tests/remote_contract_test.py", "tests/runtime_engine_test.py", "tests/security_hardening_test.py"]:
        if (source / contract_test).exists():
            tests.append(_run_capture([sys.executable, contract_test], source, 180))
    smoke = source / "tests/smoke_test.sh"
    if policy.get("require_smoke_tests", True) and smoke.exists():
        env = {**os.environ, "PAPER_REPRO_SELF_TEST": "1"}
        tests.append(_run_capture(["bash", "tests/smoke_test.sh"], source, 420, env=env))
    passed = all(test.get("passed") for test in tests)
    result = {
        "improvement_id": improvement_id,
        "tested_at": now(),
        "passed": passed,
        "tests": tests,
        "classification": _classify_improvement(improvement_id),
    }
    atomic_json(improvement_session(improvement_id) / "test-results.json", result)
    attempts = int(get_improvement(improvement_id).get("attempts", 0)) + 1
    update_improvement(improvement_id, status="tested" if passed else "test-failed", tests_passed=passed, attempts=attempts)
    return result


def _render_improvement_review(improvement_id: str) -> dict[str, Any]:
    session = improvement_session(improvement_id)
    results = read_json(session / "test-results.json", {}) or {}
    if not results.get("passed"):
        raise ReproError("内建测试尚未通过，不能生成可应用提案")
    classification = _classify_improvement(improvement_id)
    if classification["risk"] == "none":
        raise ReproError("没有检测到源码差异")
    item = get_improvement(improvement_id)
    lines = [
        "# paper-repro 自我迭代提案", "",
        f"- ID：`{improvement_id}`",
        f"- 标题：{item.get('title')}",
        f"- 风险等级：`{classification['risk']}`",
        f"- 自动应用候选：`{classification['auto_apply_eligible']}`",
        f"- 修改文件数：`{len(classification['files'])}`", "",
        "## 修改文件", "",
    ]
    lines.extend(f"- `{name}`" for name in classification["files"])
    lines.extend(["", "## 差异摘要", "", "```text", classification.get("stat", ""), "```", ""])
    if classification.get("reasons"):
        lines.extend(["## 风险依据", ""] + [f"- {reason}" for reason in classification["reasons"]] + [""])
    lines.extend(["## 测试", ""])
    for test in results.get("tests", []):
        cmd = " ".join(test.get("command", []))
        lines.append(f"- {'通过' if test.get('passed') else '失败'}：`{cmd}`（{test.get('elapsed_seconds', 0)} 秒）")
    lines.extend([
        "", "## 应用说明", "",
        "- 系统不会直接修改目标论文项目。",
        "- 应用前会备份当前 paper-repro 源码快照。",
        "- 受保护路径或中高风险修改必须经过决策层/显式确认。",
        "- 应用后需完全重启 OpenCode；原系统 issue 在真实场景验证前保持未解决。",
    ])
    review = session / "REVIEW.md"
    review.write_text("\n".join(lines) + "\n", encoding="utf-8")
    update_improvement(improvement_id, status="proposed", risk=classification["risk"], review=str(review), changed_files=classification["files"])
    return {**classification, "review": str(review), "tests_passed": True}


def _resolved_improvement_decision(run: RunPaths, improvement_id: str) -> str:
    for decision in folded_decisions(decision_records(run.decisions)):
        if decision.get("preference_key") == f"self-improvement:{improvement_id}" and decision.get("status") == "resolved":
            return str(decision.get("selected_option", ""))
    return ""


def _create_improvement_decision(paths: WorkspacePaths, run: RunPaths, improvement_id: str, classification: dict[str, Any]) -> str:
    preference_key = f"self-improvement:{improvement_id}"
    for decision in folded_decisions(decision_records(run.decisions)):
        if decision.get("preference_key") == preference_key and decision.get("status") == "pending":
            return str(decision.get("decision_id"))
    decision_id = f"DEC-{local_stamp()}-{uuid.uuid4().hex[:6]}"
    item = get_improvement(improvement_id)
    level = 3 if classification.get("risk") == "high" else 2
    record = {
        "action": "opened", "decision_id": decision_id, "ts": now(), "status": "pending",
        "title": f"是否应用系统自我迭代提案：{item.get('title')}",
        "question": f"提案 {improvement_id} 已通过回归测试，风险等级为 {classification.get('risk')}。如何处理？",
        "category": "system-level" if level == 3 else "system-self-update",
        "stage": "self-improvement", "level": level, "score": 10 if level == 3 else 7,
        "handling": "ask-user", "blocking": False,
        "options": [
            {"id": "apply", "label": "应用并备份", "consequence": "覆盖当前用户级 paper-repro 安装；需重启 OpenCode", "recommended": level == 2},
            {"id": "review", "label": "仅查看差异", "consequence": "保留提案，不修改当前安装", "recommended": level == 3},
            {"id": "discard", "label": "丢弃提案", "consequence": "不应用本次修改", "recommended": False},
        ],
        "default_option": "review", "recommended_option": "apply" if level == 2 else "review",
        "preference_key": preference_key,
        "context": json.dumps({"improvement_id": improvement_id, "review": get_improvement(improvement_id).get("review"), "files": classification.get("files")}, ensure_ascii=False),
        "confidence": 0.9, "impact": "high" if level == 3 else "medium", "reversibility": "partial",
        "user_involved": False,
    }
    append_jsonl(run.decisions, record)
    render_decisions_markdown(run)
    event(run, "self-improvement.decision.opened", improvement_id=improvement_id, decision_id=decision_id)
    return decision_id


def _apply_improvement(improvement_id: str, *, explicit: bool = False) -> dict[str, Any]:
    item = get_improvement(improvement_id)
    results = read_json(improvement_session(improvement_id) / "test-results.json", {}) or {}
    if not results.get("passed"):
        raise ReproError("不能应用未通过测试的自我迭代提案")
    classification = _classify_improvement(improvement_id)
    if classification["risk"] == "none":
        raise ReproError("没有可应用的源码差异")
    policy = self_improvement_policy()
    if not explicit and (policy.get("mode") != "guarded" or not classification.get("auto_apply_eligible")):
        raise ReproError("该提案不满足安全自动应用条件，需要决策确认或显式 --yes")
    source = improvement_source(improvement_id)
    backup = IMPROVE_BACKUPS / improvement_id / "source"
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        shutil.copytree(system_source_home(), backup, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
    env = {
        **os.environ,
        "PAPER_REPRO_SKIP_DEPENDENCIES": "1",
        "PAPER_REPRO_GLOBAL_INSTALL": "1",
        "PAPER_REPRO_SELF_PATCH_ID": improvement_id,
    }
    result = _run_capture(["bash", "bootstrap.sh"], source, timeout=600, env=env)
    log = improvement_session(improvement_id) / "apply.log"
    log.write_text(result.get("stdout", "") + "\n" + result.get("stderr", ""), encoding="utf-8")
    if not result["passed"]:
        update_improvement(improvement_id, status="apply-failed", apply_log=str(log))
        raise ReproError(f"自我迭代应用失败，已保留备份：{backup}\n{result.get('stderr')}")
    update_improvement(
        improvement_id, status="applied", applied_at=now(), backup=str(backup), apply_log=str(log),
        verification="pending-real-run", installed_version=SYSTEM_VERSION,
    )
    append_jsonl(IMPROVE_HISTORY, {"action": "applied", "improvement_id": improvement_id, "ts": now(), "backup": str(backup), "files": classification["files"]})
    return {
        "improvement_id": improvement_id,
        "status": "applied",
        "backup": str(backup),
        "apply_log": str(log),
        "restart_required": True,
        "issue_resolution": "pending-real-run",
        "message": "提案已应用。请完全重启 OpenCode，并在原问题场景中验证后执行 improve verify。",
    }


def cmd_improve_policy_show(args: argparse.Namespace) -> int:
    print(json.dumps(self_improvement_policy(), ensure_ascii=False, indent=2))
    return 0


def cmd_improve_policy_set(args: argparse.Namespace) -> int:
    policy = self_improvement_policy()
    if args.mode:
        policy["mode"] = args.mode
        policy["enabled"] = args.mode != "off"
    for field in ["auto_enqueue_system_issues", "auto_apply_safe_patches", "require_smoke_tests"]:
        value = getattr(args, field, None)
        if value is not None:
            policy[field] = value
    for field in ["max_attempts", "max_changed_files", "auto_apply_max_files"]:
        value = getattr(args, field, None)
        if value is not None:
            policy[field] = max(0, value)
    save_self_improvement_policy(policy)
    print(json.dumps(policy, ensure_ascii=False, indent=2))
    return 0


def cmd_improve_submit(args: argparse.Namespace) -> int:
    paths = None
    run = None
    try:
        paths = discover_workspace(args.workspace, args.state_root, args.latest)
        run = current_run(paths)
    except Exception:
        pass
    title = args.title or ""
    details = args.details or ""
    source_issue_id = args.issue_id or ""
    source = args.source
    if source_issue_id:
        issue = _find_system_issue(source_issue_id)
        if not issue:
            raise ReproError(f"未找到系统 issue：{source_issue_id}")
        title = title or str(issue.get("title", "系统功能问题"))
        details = details or "\n\n".join(filter(None, [str(issue.get("details", "")), str(issue.get("optimization", ""))]))
        source = "system-issue"
    if not title or not details:
        raise ReproError("submit 需要 --title 和 --details，或者提供 --issue-id")
    item = submit_improvement_candidate(
        title=title, details=details, source=source, source_issue_id=source_issue_id,
        workspace=str(paths.workspace) if paths else "", run_id=run.root.name if run else "", priority=args.priority,
    )
    print(json.dumps(item, ensure_ascii=False, indent=2))
    return 0


def cmd_improve_scan(args: argparse.Namespace) -> int:
    created = []
    for issue in folded_issues(issue_records(GLOBAL_ISSUES), id_field="issue_id"):
        if issue.get("status") != "open":
            continue
        improvement_id = enqueue_system_issue_candidate(issue)
        if improvement_id:
            created.append(improvement_id)
    print(json.dumps({"queued": sorted(set(created)), "count": len(set(created))}, ensure_ascii=False, indent=2))
    return 0


def cmd_improve_list(args: argparse.Namespace) -> int:
    items = folded_improvements()
    if args.status:
        items = [item for item in items if item.get("status") == args.status]
    print(json.dumps(items, ensure_ascii=False, indent=2))
    return 0


def cmd_improve_prepare(args: argparse.Namespace) -> int:
    print(json.dumps(_prepare_improvement(args.improvement_id, args.force), ensure_ascii=False, indent=2))
    return 0


def cmd_improve_context(args: argparse.Namespace) -> int:
    _prepare_improvement(args.improvement_id, False)
    session = improvement_session(args.improvement_id)
    payload = read_json(session / "context.json", {}) or {}
    payload["prompt"] = (session / "PROMPT.md").read_text(encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_improve_tree(args: argparse.Namespace) -> int:
    root = improvement_source(args.improvement_id)
    if not root.exists():
        raise ReproError("请先 prepare")
    files = []
    for file in sorted(root.rglob("*")):
        if file.is_file() and ".git" not in file.parts:
            rel = str(file.relative_to(root))
            if args.prefix and not rel.startswith(args.prefix):
                continue
            files.append({"path": rel, "size": file.stat().st_size})
            if len(files) >= args.limit:
                break
    print(json.dumps(files, ensure_ascii=False, indent=2))
    return 0


def cmd_improve_search(args: argparse.Namespace) -> int:
    root = improvement_source(args.improvement_id)
    pattern = re.compile(args.pattern, re.I if args.ignore_case else 0)
    results = []
    for file in root.rglob("*"):
        if not file.is_file() or ".git" in file.parts or file.stat().st_size > 2_000_000:
            continue
        try:
            lines = file.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(lines, 1):
            if pattern.search(line):
                results.append({"path": str(file.relative_to(root)), "line": lineno, "text": line[:500]})
                if len(results) >= args.limit:
                    print(json.dumps(results, ensure_ascii=False, indent=2))
                    return 0
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


def cmd_improve_read(args: argparse.Namespace) -> int:
    target = _safe_improvement_path(args.improvement_id, args.path)
    if not target.is_file():
        raise ReproError(f"文件不存在：{args.path}")
    if target.stat().st_size > args.max_kb * 1024:
        raise ReproError(f"文件超过读取上限 {args.max_kb} KiB")
    lines = target.read_text(encoding="utf-8").splitlines()
    start = max(1, args.start)
    end = min(len(lines), args.end if args.end > 0 else len(lines))
    print("\n".join(f"{index}: {lines[index-1]}" for index in range(start, end + 1)))
    return 0


def cmd_improve_write(args: argparse.Namespace) -> int:
    item = get_improvement(args.improvement_id)
    policy = self_improvement_policy()
    if item.get("status") == "test-failed" and int(item.get("attempts", 0)) >= int(policy.get("max_attempts", 2)):
        raise ReproError("已达到允许的自动修复轮数上限，请保留现场并交由用户审查")
    target = _safe_improvement_path(args.improvement_id, args.path)
    if args.content_base64:
        try:
            content = base64.b64decode(args.content_base64).decode("utf-8")
        except Exception as exc:
            raise ReproError(f"无效的 base64 内容：{exc}") from exc
    elif args.stdin:
        content = sys.stdin.read()
    else:
        content = args.content or ""
    if len(content.encode("utf-8")) > args.max_kb * 1024:
        raise ReproError(f"写入内容超过上限 {args.max_kb} KiB")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.is_symlink():
        raise ReproError("禁止覆盖符号链接")
    target.write_text(content, encoding="utf-8")
    update_improvement(args.improvement_id, status="editing", last_modified=args.path)
    print(json.dumps({"path": args.path, "bytes": len(content.encode('utf-8')), "status": "written"}, ensure_ascii=False, indent=2))
    return 0


def cmd_improve_test(args: argparse.Namespace) -> int:
    print(json.dumps(_test_improvement(args.improvement_id), ensure_ascii=False, indent=2))
    return 0


def cmd_improve_diff(args: argparse.Namespace) -> int:
    data = _improvement_diff(args.improvement_id)
    if args.summary:
        data.pop("diff", None)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_improve_propose(args: argparse.Namespace) -> int:
    print(json.dumps(_render_improvement_review(args.improvement_id), ensure_ascii=False, indent=2))
    return 0


def cmd_improve_auto(args: argparse.Namespace) -> int:
    classification = _classify_improvement(args.improvement_id)
    policy = self_improvement_policy()
    if policy.get("mode") == "off":
        raise ReproError("自我迭代已关闭")
    if policy.get("mode") == "guarded" and classification.get("auto_apply_eligible"):
        print(json.dumps(_apply_improvement(args.improvement_id, explicit=False), ensure_ascii=False, indent=2))
        return 0
    paths = None
    run = None
    try:
        paths = discover_workspace(args.workspace, args.state_root, args.latest)
        run = current_run(paths)
    except Exception:
        pass
    if paths and run:
        selected = _resolved_improvement_decision(run, args.improvement_id)
        if selected == "apply":
            print(json.dumps(_apply_improvement(args.improvement_id, explicit=True), ensure_ascii=False, indent=2))
            return 0
        if selected == "discard":
            update_improvement(args.improvement_id, status="discarded", discarded_at=now())
            print(json.dumps({"improvement_id": args.improvement_id, "status": "discarded"}, ensure_ascii=False, indent=2))
            return 0
        decision_id = _create_improvement_decision(paths, run, args.improvement_id, classification)
        print(json.dumps({
            "improvement_id": args.improvement_id, "status": "awaiting-decision", "decision_id": decision_id,
            "risk": classification.get("risk"), "review": get_improvement(args.improvement_id).get("review"),
        }, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps({
        "improvement_id": args.improvement_id, "status": "awaiting-explicit-approval",
        "risk": classification.get("risk"), "review": get_improvement(args.improvement_id).get("review"),
        "next": f"paper-repro improve apply {args.improvement_id} --yes",
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_improve_apply(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ReproError("应用系统更新需要显式 --yes")
    print(json.dumps(_apply_improvement(args.improvement_id, explicit=True), ensure_ascii=False, indent=2))
    return 0


def cmd_improve_verify(args: argparse.Namespace) -> int:
    item = get_improvement(args.improvement_id)
    if item.get("status") != "applied":
        raise ReproError("只有已应用提案可以进行真实场景验证")
    status = "verified" if args.passed else "verification-failed"
    update_improvement(args.improvement_id, status=status, verified_at=now(), verification_note=args.note)
    issue_id = str(item.get("source_issue_id", ""))
    if args.passed and issue_id:
        resolution = {
            "action": "resolved", "issue_id": issue_id, "ts": now(), "status": "resolved",
            "resolution": f"由自我迭代任务 {args.improvement_id} 修复，并通过真实场景验证。{args.note}",
        }
        append_jsonl(GLOBAL_ISSUES, resolution)
        workspace = str(item.get("workspace", ""))
        if workspace:
            paths = WorkspacePaths(workspace=Path(workspace).expanduser().resolve(), state_home=Path(workspace).expanduser().resolve() / ".paper-repro")
            append_jsonl(paths.system / "issues.jsonl", resolution)
            render_issue_markdown(paths.system / "SYSTEM_ISSUES.md", "系统功能与优化问题汇总", issue_records(paths.system / "issues.jsonl"), kind="system")
    publication_candidate = {}
    if args.passed:
        try:
            publication_candidate = enqueue_publication_after_improvement(args.improvement_id)
            update_improvement(args.improvement_id, publication_candidate=publication_candidate.get("publication_id", ""))
        except Exception as exc:
            publication_candidate = {"status": "enqueue-failed", "message": redact(str(exc))}
    print(json.dumps({"improvement_id": args.improvement_id, "status": status, "source_issue_id": issue_id, "publication_candidate": publication_candidate}, ensure_ascii=False, indent=2))
    return 0


def cmd_improve_discard(args: argparse.Namespace) -> int:
    update_improvement(args.improvement_id, status="discarded", discarded_at=now(), discard_reason=args.reason)
    if args.delete_session:
        shutil.rmtree(improvement_session(args.improvement_id), ignore_errors=True)
    print(json.dumps({"improvement_id": args.improvement_id, "status": "discarded"}, ensure_ascii=False, indent=2))
    return 0


def cmd_improve_rollback(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ReproError("回滚需要显式 --yes")
    backup = IMPROVE_BACKUPS / args.improvement_id / "source"
    if not (backup / "bootstrap.sh").exists():
        raise ReproError(f"找不到回滚备份：{backup}")
    env = {**os.environ, "PAPER_REPRO_SKIP_DEPENDENCIES": "1", "PAPER_REPRO_GLOBAL_INSTALL": "1"}
    result = _run_capture(["bash", "bootstrap.sh"], backup, timeout=600, env=env)
    log = improvement_session(args.improvement_id) / "rollback.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(result.get("stdout", "") + "\n" + result.get("stderr", ""), encoding="utf-8")
    if not result["passed"]:
        raise ReproError(result.get("stderr") or "回滚失败")
    update_improvement(args.improvement_id, status="rolled-back", rolled_back_at=now(), rollback_log=str(log))
    print(json.dumps({"improvement_id": args.improvement_id, "status": "rolled-back", "restart_required": True}, ensure_ascii=False, indent=2))
    return 0


def cmd_improve_status(args: argparse.Namespace) -> int:
    item = get_improvement(args.improvement_id)
    session = improvement_session(args.improvement_id)
    payload = dict(item)
    payload["session_exists"] = session.exists()
    payload["source_path"] = str(session / "source") if session.exists() else ""
    payload["test_results"] = read_json(session / "test-results.json", {}) if session.exists() else {}
    if session.exists() and (session / "source/.git").exists():
        payload["classification"] = _classify_improvement(args.improvement_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------------------
# Privacy-preserving GitHub publication
# ---------------------------------------------------------------------------

PUBLISH_MODES = {
    "off": "关闭",
    "manual": "仅手动",
    "review": "准备与扫描自动，上传前确认",
}
PUBLISH_VISIBILITIES = {"public", "private", "internal"}
PUBLISH_AUTH_METHODS = {"gh", "token"}
PUBLISH_EXISTING_MODES = {"pull-request", "direct"}
PUBLISH_SYNC_MODES = {"managed-mirror", "preserve-extra"}
PUBLISH_AFTER_VERIFIED = {"off", "notify", "prepare"}
PUBLISH_ALLOWLIST = (
    "scripts", "schemas", "docs", "configs", ".opencode", ".github", "tests",
    "bootstrap.sh", "README.md", "CONTRIBUTING.md", "AGENTS.md", "CHANGELOG_CN.md",
    "USAGE_CN.md", "VERSION", "opencode.jsonc", ".gitignore",
)
PUBLISH_DENY_PATH_PATTERNS = [
    re.compile(r"(^|/)(\.env(?:\..*)?|auth\.json|credentials(?:\..*)?|secrets?(?:\..*)?|id_rsa(?:\.pub)?|id_ed25519(?:\.pub)?|.*\.(?:pem|p12|pfx|key))$", re.I),
    re.compile(r"(^|/)(\.paper-repro|runs?|logs?|cache|datasets?|models?|checkpoints?|wandb)(/|$)", re.I),
    re.compile(r"\.(?:pdf|pt|pth|ckpt|safetensors|onnx|npz|npy|parquet|arrow|sqlite|db)$", re.I),
]
PUBLISH_SECRET_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"\b(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9_]{20,})\b")),
    ("huggingface-token", re.compile(r"\bhf_[A-Za-z0-9]{20,}\b")),
    ("generic-api-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("authorization-header", re.compile(r"(?i)Authorization\s*[:=]\s*(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{12,}")),
    ("credential-assignment", re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|client[_-]?secret|private[_-]?key)\b\s*[:=]\s*[\"'](?!<|\{|\$|example|your-|xxxx)[^\"']{12,}[\"']")),
]


def default_github_publish_policy() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "enabled": True,
        "mode": "review",
        "host": "github.com",
        "owner": "",
        "repository": "",
        "visibility": "",
        "description": "OpenCode-based auditable paper reproduction automation",
        "default_branch": "main",
        "license": "MIT",
        "copyright_holder": "",
        "auth_method": "gh",
        "token_env": "GITHUB_PUBLISH_TOKEN",
        "existing_repo_mode": "pull-request",
        "sync_mode": "managed-mirror",
        "after_verified": "notify",
        "require_clean_scan": True,
        "require_explicit_approval": True,
        "approval_ttl_seconds": 3600,
        "max_file_bytes": 5 * 1024 * 1024,
        "enable_push_protection": True,
    }


def github_publish_policy() -> dict[str, Any]:
    policy = merge_dict(default_github_publish_policy(), load_unified_config().get("github_publish", {}) or {})
    if policy.get("mode") not in PUBLISH_MODES:
        policy["mode"] = "review"
    if policy.get("visibility") and policy.get("visibility") not in PUBLISH_VISIBILITIES:
        policy["visibility"] = ""
    if policy.get("auth_method") not in PUBLISH_AUTH_METHODS:
        policy["auth_method"] = "gh"
    if policy.get("existing_repo_mode") not in PUBLISH_EXISTING_MODES:
        policy["existing_repo_mode"] = "pull-request"
    if policy.get("sync_mode") not in PUBLISH_SYNC_MODES:
        policy["sync_mode"] = "managed-mirror"
    if policy.get("after_verified") not in PUBLISH_AFTER_VERIFIED:
        policy["after_verified"] = "notify"
    policy["enabled"] = bool(policy.get("enabled", True)) and policy.get("mode") != "off"
    return policy


def save_github_publish_policy(policy: dict[str, Any]) -> None:
    config = load_unified_config()
    policy["updated_at"] = now()
    config["github_publish"] = policy
    save_unified_config(config)


def _publish_target(policy: dict[str, Any]) -> str:
    owner = str(policy.get("owner", "")).strip()
    repo = str(policy.get("repository", "")).strip()
    return f"{owner}/{repo}" if owner and repo else ""


def publish_records() -> list[dict[str, Any]]:
    return issue_records(PUBLISH_QUEUE)


def folded_publications(records: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    folded: dict[str, dict[str, Any]] = {}
    for record in records if records is not None else publish_records():
        publication_id = record.get("publication_id")
        if not publication_id:
            continue
        if record.get("action", "opened") == "opened":
            folded[publication_id] = dict(record)
            folded[publication_id]["status"] = record.get("status", "queued")
        elif publication_id in folded:
            folded[publication_id].update({k: v for k, v in record.items() if k != "action"})
    return sorted(folded.values(), key=lambda item: item.get("created_at", item.get("ts", "")), reverse=True)


def get_publication(publication_id: str) -> dict[str, Any]:
    for item in folded_publications():
        if item.get("publication_id") == publication_id:
            return item
    raise ReproError(f"未找到开源发布任务：{publication_id}")


def update_publication(publication_id: str, **fields: Any) -> dict[str, Any]:
    record = {"action": "updated", "publication_id": publication_id, "ts": now(), **fields}
    append_jsonl(PUBLISH_QUEUE, record)
    append_jsonl(PUBLISH_HISTORY, record)
    return get_publication(publication_id)


def publication_session(publication_id: str) -> Path:
    return PUBLISH_SESSIONS / publication_id


def publication_snapshot(publication_id: str) -> Path:
    return publication_session(publication_id) / "snapshot"


def _safe_publication_path(publication_id: str, relative: str) -> Path:
    root = publication_snapshot(publication_id).resolve()
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or ".git" in rel.parts:
        raise ReproError("只允许访问发布快照中的安全相对路径")
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ReproError("路径越过发布快照边界") from exc
    return target


def _known_private_literals() -> list[tuple[str, str, str]]:
    literals: list[tuple[str, str, str]] = []
    home = str(Path.home().resolve())
    if home not in {"/", ""}:
        literals.append(("home", home, "$HOME"))
    conda_prefix = os.environ.get("CONDA_PREFIX", "").strip()
    if conda_prefix:
        literals.append(("control-conda", conda_prefix, "/path/to/conda/envs/paper-repro-control"))
    install_home = os.environ.get("PAPER_REPRO_INSTALL_HOME", "").strip()
    if install_home:
        literals.append(("install-home", install_home, "/path/to/conda/envs/paper-repro-control/share/opencode-paper-repro"))
    hostname = platform.node().strip()
    if len(hostname) >= 5 and hostname.lower() not in {"localhost", "localhost.localdomain"}:
        literals.append(("hostname", hostname, "example-host"))
    registry = read_json(REGISTRY_FILE, {}) or {}
    workspaces = registry.get("workspaces", {}) if isinstance(registry, dict) else {}
    if isinstance(workspaces, dict):
        for workspace in workspaces:
            value = str(workspace).strip()
            if not value:
                continue
            literals.append(("workspace", value, "/path/to/project"))
            name = Path(value).name
            distinctive = len(name) >= 8 and (bool(re.search(r"[-_.0-9]", name)) or any(ch.isupper() for ch in name))
            if distinctive:
                literals.append(("workspace-name", name, "example-project"))
    # Prefer longest matches first so nested paths are normalized before $HOME.
    unique: dict[str, tuple[str, str, str]] = {}
    for item in literals:
        unique[item[1]] = item
    return sorted(unique.values(), key=lambda item: len(item[1]), reverse=True)


def _copy_public_source(source: Path, destination: Path) -> list[str]:
    copied: list[str] = []
    destination.mkdir(parents=True, exist_ok=True)
    for name in PUBLISH_ALLOWLIST:
        src = source / name
        if not src.exists():
            continue
        dst = destination / name
        links = sec.find_symlinks(src)
        if links:
            sample = [str(item.relative_to(source)) for item in links[:10]]
            raise ReproError(f"源码快照包含符号链接，发布 fail-closed：{sample}")
        if src.is_dir():
            shutil.copytree(
                src, dst,
                symlinks=True,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.zip", ".paper-repro", "runs", "dist"),
            )
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        copied.append(name)
    return copied


def _sanitize_public_text(snapshot: Path) -> list[dict[str, Any]]:
    transformations: list[dict[str, Any]] = []
    literals = _known_private_literals()
    for file in snapshot.rglob("*"):
        if not file.is_file() or file.is_symlink() or file.stat().st_size > 2_000_000:
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        original = text
        for kind, value, replacement in literals:
            if value and value in text:
                count = text.count(value)
                text = text.replace(value, replacement)
                transformations.append({"path": str(file.relative_to(snapshot)), "kind": kind, "count": count})
        if text != original:
            file.write_text(text, encoding="utf-8")
    return transformations


def _ensure_public_gitignore(snapshot: Path) -> None:
    path = snapshot / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    additions = """

# Local paper-repro state and credentials
.paper-repro/
.repro/
runs/
.env
.env.*
!.env.example
*.pem
*.key
*.p12
*.pfx
auth.json
credentials.json
secrets.json
config.local.json

# Reproduction assets and private project material
*.pdf
*.pt
*.pth
*.ckpt
*.safetensors
*.onnx
*.parquet
*.arrow
wandb/
datasets/
models/
checkpoints/
""".strip() + "\n"
    if "# Local paper-repro state and credentials" not in existing:
        path.write_text(existing.rstrip() + "\n\n" + additions, encoding="utf-8")


def _write_public_governance_files(snapshot: Path, policy: dict[str, Any]) -> None:
    security = """# Security Policy

Please do not disclose credentials, private datasets, unpublished papers, project logs, or personal paths in public issues.

For a suspected credential leak:
1. Revoke or rotate the credential immediately.
2. Do not bypass GitHub push protection.
3. Open a private security advisory or contact the repository owner through a private channel.

The public repository must contain only the sanitized paper-repro system source. Runtime workspaces, `.paper-repro/`, model/data assets, API responses, and user configuration are out of scope and must never be committed.
"""
    privacy = """# Publication Privacy Boundary

This repository is generated from a clean system-source snapshot, not from any paper reproduction workspace.

The publication pipeline excludes and scans for:
- API keys, tokens, passwords, private keys and authentication files;
- project repositories, PDF papers, datasets, checkpoints, predictions and logs;
- `.paper-repro/`, Conda environment metadata and user configuration;
- absolute home/workspace paths, hostnames and known project identifiers.

A public push is blocked unless the snapshot passes the local privacy scan and the user explicitly approves the exact repository and visibility.
"""
    (snapshot / "SECURITY.md").write_text(security, encoding="utf-8")
    (snapshot / "PRIVACY.md").write_text(privacy, encoding="utf-8")
    if str(policy.get("license", "MIT")).upper() == "MIT":
        holder = str(policy.get("copyright_holder") or policy.get("owner") or "paper-repro contributors").strip()
        year = datetime.now().year
        license_text = f"""MIT License

Copyright (c) {year} {holder}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the \"Software\"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
        (snapshot / "LICENSE").write_text(license_text, encoding="utf-8")


def _snapshot_manifest(snapshot: Path) -> dict[str, Any]:
    files = []
    total = 0
    for file in sorted(snapshot.rglob("*")):
        if not file.is_file() or ".git" in file.parts:
            continue
        size = file.stat().st_size
        total += size
        files.append({
            "path": str(file.relative_to(snapshot)),
            "size": size,
            "sha256": sha256_file(file),
        })
    digest = hashlib.sha256(json.dumps(files, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return {"files": files, "file_count": len(files), "total_bytes": total, "manifest_sha256": digest}


def _secret_variants(name: str, value: str) -> list[tuple[str, str]]:
    if len(value) < 8:
        return []
    variants = [(name, value)]
    try:
        variants.append((f"{name}:base64", base64.b64encode(value.encode("utf-8")).decode("ascii")))
        variants.append((f"{name}:urlencoded", urllib.parse.quote(value, safe="")))
    except Exception:
        pass
    return [(label, token) for label, token in variants if len(token) >= 8]


def _scan_public_snapshot(publication_id: str) -> dict[str, Any]:
    snapshot = publication_snapshot(publication_id)
    if not snapshot.exists():
        raise ReproError("发布快照尚未准备")
    policy = github_publish_policy()
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if str(policy.get("visibility", "")) == "public" and str(policy.get("license", "MIT")) == "none":
        blockers.append({
            "type": "missing-license",
            "path": "LICENSE",
            "message": "公开仓库必须配置开源许可证；当前策略为 none",
        })
    secrets = load_secrets_store().get("secrets", {})
    secret_variants = []
    for name, value in secrets.items():
        secret_variants.extend(_secret_variants(name, value))
    # Also protect credentials that are currently injected into the process but not
    # persisted in paper-repro's unified config (for example GH_TOKEN or vendor keys).
    env_secret_name = re.compile(r"(?i)(?:^|_)(?:token|secret|password|passwd|api[_-]?key|access[_-]?key|auth|credential)(?:$|_)")
    for name, value in os.environ.items():
        if env_secret_name.search(name) and isinstance(value, str) and len(value) >= 8:
            secret_variants.extend(_secret_variants(f"env:{name}", value))
    private_literals = _known_private_literals()
    max_bytes = int(policy.get("max_file_bytes", 5 * 1024 * 1024))
    email_re = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
    ip_re = re.compile(r"\b(?:10\.(?:\d{1,3}\.){2}\d{1,3}|192\.168\.(?:\d{1,3}\.)\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.(?:\d{1,3}\.)\d{1,3})\b")

    for path in sorted(snapshot.rglob("*")):
        rel = str(path.relative_to(snapshot))
        if path.is_symlink():
            blockers.append({"type": "symlink", "path": rel, "message": "禁止发布符号链接"})
            continue
        if not path.is_file():
            continue
        for pattern in PUBLISH_DENY_PATH_PATTERNS:
            if pattern.search(rel):
                blockers.append({"type": "sensitive-path", "path": rel, "message": "路径匹配私密/项目资产阻断规则"})
                break
        size = path.stat().st_size
        if size > max_bytes:
            blockers.append({"type": "oversized-file", "path": rel, "size": size, "message": "单文件超过公开快照上限"})
            continue
        raw = path.read_bytes()
        if b"\x00" in raw:
            blockers.append({"type": "binary-file", "path": rel, "size": size, "message": "公开系统源码默认不允许未知二进制文件"})
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            blockers.append({"type": "non-utf8", "path": rel, "message": "无法审计的非 UTF-8 文件"})
            continue
        lines = text.splitlines()
        for label, token in secret_variants:
            if token and token in text:
                blockers.append({"type": "known-secret", "secret_name": label, "path": rel, "message": "发现统一配置中的真实密钥值或其编码形式"})
        for label, pattern in PUBLISH_SECRET_PATTERNS:
            for lineno, line in enumerate(lines, 1):
                if pattern.search(line):
                    blockers.append({"type": label, "path": rel, "line": lineno, "message": "发现疑似凭据"})
                    if len([item for item in blockers if item.get("path") == rel and item.get("type") == label]) >= 5:
                        break
        for kind, literal, _replacement in private_literals:
            if literal and literal in text:
                blockers.append({"type": "private-literal", "kind": kind, "path": rel, "message": "发现当前机器或项目的私密标识"})
        for lineno, line in enumerate(lines, 1):
            for email in email_re.findall(line):
                lower = email.lower()
                if lower.endswith("@example.com") or "users.noreply.github.com" in lower or lower in {"noreply@users.noreply.github.com", "git@github.com"}:
                    continue
                warnings.append({"type": "email", "path": rel, "line": lineno, "value": "<REDACTED>", "message": "发现可能公开的邮箱，请人工确认"})
            if ip_re.search(line):
                warnings.append({"type": "private-ip", "path": rel, "line": lineno, "message": "发现私网 IP，请确认不是运行环境信息"})

    optional = {"gitleaks": {"available": bool(shutil.which("gitleaks")), "executed": False}}
    if shutil.which("gitleaks"):
        report_path = publication_session(publication_id) / "gitleaks.json"
        commands = [
            ["gitleaks", "dir", str(snapshot), "--redact", "--report-format", "json", "--report-path", str(report_path), "--exit-code", "1"],
            ["gitleaks", "detect", "--source", str(snapshot), "--no-git", "--redact", "--report-format", "json", "--report-path", str(report_path)],
        ]
        result = None
        for command in commands:
            result = _run_capture(command, snapshot, timeout=180)
            stderr = str(result.get("stderr", ""))
            if "unknown command" not in stderr.lower() and "unknown flag" not in stderr.lower():
                break
        optional["gitleaks"] = {"available": True, "executed": True, "passed": bool(result and result.get("passed")), "report": str(report_path) if report_path.exists() else ""}
        if result and not result.get("passed") and report_path.exists():
            findings = read_json(report_path, []) or []
            blockers.append({"type": "gitleaks", "path": str(report_path), "count": len(findings), "message": "gitleaks 检测到疑似密钥"})

    manifest = _snapshot_manifest(snapshot)
    passed = not blockers
    report = {
        "schema_version": 1,
        "publication_id": publication_id,
        "scanned_at": now(),
        "system_version": SYSTEM_VERSION,
        "target": _publish_target(policy),
        "visibility": policy.get("visibility", ""),
        "passed": passed,
        "blocking_findings": blockers,
        "warnings": warnings,
        "optional_scanners": optional,
        "manifest": manifest,
    }
    session = publication_session(publication_id)
    atomic_json(session / "PRIVACY_SCAN.json", report)
    lines = [
        "# GitHub 开源发布隐私审查",
        "",
        f"- 发布任务：`{publication_id}`",
        f"- 系统版本：`{SYSTEM_VERSION}`",
        f"- 目标仓库：`{_publish_target(policy) or '尚未配置'}`",
        f"- 可见性：`{policy.get('visibility') or '尚未配置'}`",
        f"- 扫描结论：**{'通过' if passed else '阻断'}**",
        f"- 文件数量：{manifest['file_count']}",
        f"- 快照摘要：`{manifest['manifest_sha256']}`",
        "",
        "## 阻断项",
    ]
    if blockers:
        lines.extend(f"- `{item.get('type')}` · `{item.get('path', '')}` · {item.get('message', '')}" for item in blockers)
    else:
        lines.append("- 无")
    lines.extend(["", "## 人工复核警告"])
    if warnings:
        lines.extend(f"- `{item.get('type')}` · `{item.get('path', '')}:{item.get('line', '')}` · {item.get('message', '')}" for item in warnings)
    else:
        lines.append("- 无")
    lines.extend([
        "",
        "## 强制边界",
        "- 本报告和本地发布会话不会进入公开仓库。",
        "- 真实 Token 不会显示在报告中。",
        "- 任何阻断项都禁止上传；不提供绕过扫描或 GitHub push protection 的选项。",
    ])
    (session / "REVIEW.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    update_publication(publication_id, status="scanned" if passed else "blocked", scan_passed=passed, manifest_sha256=manifest["manifest_sha256"], review=str(session / "REVIEW.md"))
    return report


def _prepare_publication(*, improvement_id: str = "", force: bool = False) -> dict[str, Any]:
    policy = github_publish_policy()
    if not policy.get("enabled"):
        raise ReproError("GitHub 开源发布功能已关闭")
    publication_id = f"PUB-{local_stamp()}-{uuid.uuid4().hex[:6]}"
    session = publication_session(publication_id)
    snapshot = publication_snapshot(publication_id)
    if force and session.exists():
        shutil.rmtree(session)
    session.mkdir(parents=True, exist_ok=True)
    source = system_source_home()
    copied = _copy_public_source(source, snapshot)
    transformations = _sanitize_public_text(snapshot)
    _ensure_public_gitignore(snapshot)
    _write_public_governance_files(snapshot, policy)
    manifest = _snapshot_manifest(snapshot)
    record = {
        "action": "opened",
        "publication_id": publication_id,
        "created_at": now(),
        "updated_at": now(),
        "system_version": SYSTEM_VERSION,
        "improvement_id": improvement_id,
        "target": _publish_target(policy),
        "visibility": policy.get("visibility", ""),
        "status": "prepared",
        "session": str(session),
        "snapshot": str(snapshot),
        "manifest_sha256": manifest["manifest_sha256"],
        "copied_top_level": copied,
        "sanitized_replacements": len(transformations),
    }
    append_jsonl(PUBLISH_QUEUE, record)
    append_jsonl(PUBLISH_HISTORY, record)
    atomic_json(session / "PUBLISH_MANIFEST.json", manifest)
    atomic_json(session / "SANITIZATION.json", {"transformations": transformations})
    return {**record, "manifest": manifest}


def _publication_policy_fingerprint(policy: dict[str, Any]) -> str:
    public_fields = {
        key: policy.get(key, "")
        for key in [
            "host", "owner", "repository", "visibility", "description",
            "default_branch", "license", "copyright_holder",
            "existing_repo_mode", "sync_mode", "git_author_name", "git_author_email",
        ]
    }
    payload = json.dumps(public_fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _approval_file(publication_id: str) -> Path:
    return publication_session(publication_id) / "APPROVAL.json"


def _valid_publish_approval(publication_id: str, policy: dict[str, Any], manifest_sha: str) -> tuple[bool, str]:
    approval = read_json(_approval_file(publication_id), {}) or {}
    if not approval:
        return False, "尚未批准"
    if approval.get("target") != _publish_target(policy) or approval.get("visibility") != policy.get("visibility"):
        return False, "仓库或可见性已变化，需要重新批准"
    if approval.get("manifest_sha256") != manifest_sha:
        return False, "快照内容已变化，需要重新扫描并批准"
    if approval.get("policy_fingerprint") != _publication_policy_fingerprint(policy):
        return False, "公开元数据或发布策略已变化，需要重新批准"
    expires = float(approval.get("expires_epoch", 0))
    if time.time() > expires:
        return False, "批准已过期"
    return True, "approved"


def _github_env(policy: dict[str, Any]) -> dict[str, str]:
    env = dict(os.environ)
    env["GH_HOST"] = str(policy.get("host", "github.com"))
    if policy.get("auth_method") == "token":
        token_env = str(policy.get("token_env", "GITHUB_PUBLISH_TOKEN"))
        token = env.get(token_env, "")
        if not token:
            raise ReproError(f"未配置发布 Token。请执行：paper-repro secrets set {token_env}")
        env["GH_TOKEN"] = token
    return env


def _github_auth_status(policy: dict[str, Any]) -> dict[str, Any]:
    method = str(policy.get("auth_method", "gh"))
    host = str(policy.get("host", "github.com"))
    if not shutil.which("gh"):
        return {"ready": False, "method": method, "message": "未找到 GitHub CLI (gh)"}
    if method == "token":
        token_env = str(policy.get("token_env", "GITHUB_PUBLISH_TOKEN"))
        return {"ready": bool(os.environ.get(token_env)), "method": method, "token_env": token_env, "message": "Token 已配置" if os.environ.get(token_env) else "Token 未配置"}
    result = _run_capture(["gh", "auth", "status", "--hostname", host], Path.cwd(), timeout=30, env=dict(os.environ))
    return {"ready": result.get("passed", False), "method": method, "host": host, "message": result.get("stdout") or result.get("stderr")}


def _replace_tree_from_snapshot(snapshot: Path, destination: Path, sync_mode: str = "managed-mirror") -> None:
    if sync_mode == "managed-mirror":
        for child in destination.iterdir():
            if child.name == ".git":
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink(missing_ok=True)
    for child in snapshot.iterdir():
        dst = destination / child.name
        if child.is_dir():
            if dst.exists() and sync_mode == "preserve-extra":
                shutil.copytree(child, dst, dirs_exist_ok=True)
            else:
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(child, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, dst)


def _git_commit_identity(policy: dict[str, Any]) -> tuple[str, str]:
    owner = str(policy.get("owner", "paper-repro")) or "paper-repro"
    name = str(policy.get("git_author_name", "")).strip() or f"{owner} paper-repro publisher"
    email = str(policy.get("git_author_email", "")).strip() or f"{owner}@users.noreply.github.com"
    return name, email


def _publish_to_github(publication_id: str) -> dict[str, Any]:
    item = get_publication(publication_id)
    policy = github_publish_policy()
    target = _publish_target(policy)
    if not target:
        raise ReproError("尚未配置 GitHub owner/repository")
    if not policy.get("visibility"):
        raise ReproError("尚未配置仓库可见性")
    scan = read_json(publication_session(publication_id) / "PRIVACY_SCAN.json", {}) or {}
    if not scan or not scan.get("passed"):
        raise ReproError("隐私扫描未通过，禁止上传")
    manifest_sha = str(scan.get("manifest", {}).get("manifest_sha256", ""))
    approved, reason = _valid_publish_approval(publication_id, policy, manifest_sha)
    if not approved:
        raise ReproError(f"没有有效的最终发布批准：{reason}")
    auth = _github_auth_status(policy)
    if not auth.get("ready"):
        if policy.get("auth_method") == "gh":
            raise ReproError("GitHub CLI 尚未登录。请先执行 gh auth login；不要在聊天中粘贴 Token。")
        raise ReproError(str(auth.get("message", "GitHub 认证不可用")))
    env = _github_env(policy)
    snapshot = publication_snapshot(publication_id)
    session = publication_session(publication_id)
    remote_work = session / "remote-work"
    shutil.rmtree(remote_work, ignore_errors=True)
    host = str(policy.get("host", "github.com"))
    view = _run_capture(["gh", "repo", "view", target, "--json", "nameWithOwner,isPrivate,visibility,url,defaultBranchRef"], session, timeout=60, env=env)
    exists = bool(view.get("passed"))
    remote_info: dict[str, Any] = {}
    if exists:
        try:
            remote_info = json.loads(str(view.get("stdout", "{}")))
        except json.JSONDecodeError:
            remote_info = {}
        remote_visibility = str(remote_info.get("visibility", "")).lower()
        if remote_visibility and remote_visibility != str(policy.get("visibility", "")).lower():
            raise ReproError(
                f"目标仓库当前可见性为 {remote_visibility}，配置要求 {policy.get('visibility')}。"
                "系统不会自动改变仓库可见性；请先明确调整配置或在 GitHub 中人工修改。"
            )
    actions: list[dict[str, Any]] = []
    if not exists:
        create_cmd = ["gh", "repo", "create", target, f"--{policy.get('visibility')}", "--description", str(policy.get("description", ""))]
        created = _run_capture(create_cmd, session, timeout=120, env=env)
        actions.append(created)
        if not created.get("passed"):
            raise ReproError(created.get("stderr") or "GitHub 仓库创建失败")
    clone = _run_capture(["gh", "repo", "clone", target, str(remote_work), "--", "--depth", "1"], session, timeout=180, env=env)
    actions.append(clone)
    if not clone.get("passed"):
        raise ReproError(clone.get("stderr") or "GitHub 仓库克隆失败")
    name, email = _git_commit_identity(policy)
    _run_capture(["git", "config", "user.name", name], remote_work, env=env)
    _run_capture(["git", "config", "user.email", email], remote_work, env=env)
    default_branch = str(policy.get("default_branch", "main"))
    if exists and isinstance(remote_info.get("defaultBranchRef"), dict):
        default_branch = str(remote_info.get("defaultBranchRef", {}).get("name") or default_branch)
    version = SYSTEM_VERSION
    if exists and policy.get("existing_repo_mode") == "pull-request":
        branch = f"paper-repro/update-v{version}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        checkout = _run_capture(["git", "checkout", "-b", branch], remote_work, env=env)
        actions.append(checkout)
        if not checkout.get("passed"):
            raise ReproError(checkout.get("stderr") or "创建发布分支失败")
    else:
        branch = default_branch
        checkout = _run_capture(["git", "checkout", "-B", branch], remote_work, env=env)
        actions.append(checkout)
        if not checkout.get("passed"):
            raise ReproError(checkout.get("stderr") or "切换默认发布分支失败")
    _replace_tree_from_snapshot(snapshot, remote_work, str(policy.get("sync_mode", "managed-mirror")))
    # Final scan the exact tree about to be committed, excluding .git.
    final_snapshot = session / "final-tree"
    shutil.rmtree(final_snapshot, ignore_errors=True)
    shutil.copytree(remote_work, final_snapshot, ignore=shutil.ignore_patterns(".git"))
    original_snapshot = publication_snapshot(publication_id)
    # Temporarily point scanner at final tree by swapping directories safely.
    backup_snapshot = session / "snapshot.pre-final-scan"
    if backup_snapshot.exists():
        shutil.rmtree(backup_snapshot)
    original_snapshot.rename(backup_snapshot)
    final_snapshot.rename(original_snapshot)
    try:
        final_scan = _scan_public_snapshot(publication_id)
    finally:
        shutil.rmtree(original_snapshot, ignore_errors=True)
        backup_snapshot.rename(original_snapshot)
    if not final_scan.get("passed"):
        raise ReproError("最终提交树隐私扫描失败，上传已阻断")
    add = _run_capture(["git", "add", "--all"], remote_work, env=env)
    actions.append(add)
    staged = _run_capture(["git", "diff", "--cached", "--quiet"], remote_work, env=env)
    if staged.get("passed"):
        update_publication(publication_id, status="no-changes", repository=target)
        return {"publication_id": publication_id, "status": "no-changes", "repository": target, "actions": actions}
    commit = _run_capture(["git", "commit", "-m", f"Publish paper-repro v{version}"], remote_work, timeout=120, env=env)
    actions.append(commit)
    if not commit.get("passed"):
        raise ReproError(commit.get("stderr") or "提交失败")
    push = _run_capture(["git", "push", "--set-upstream", "origin", branch], remote_work, timeout=300, env=env)
    actions.append(push)
    if not push.get("passed"):
        message = push.get("stderr") or "推送失败"
        if "secret" in message.lower() or "push protection" in message.lower():
            raise ReproError("GitHub push protection 阻止了推送。禁止绕过；请撤销/轮换真实密钥并清理快照后重试。")
        raise ReproError(message)
    pr_url = ""
    if exists and policy.get("existing_repo_mode") == "pull-request":
        pr = _run_capture([
            "gh", "pr", "create", "--repo", target, "--head", branch, "--base", default_branch,
            "--title", f"Publish paper-repro v{version}",
            "--body", "Automated sanitized system-source publication. The snapshot passed local secret, path, project-data and personal-information scans. Please review before merging.",
        ], remote_work, timeout=120, env=env)
        actions.append(pr)
        if not pr.get("passed"):
            raise ReproError(pr.get("stderr") or "创建 Pull Request 失败")
        pr_url = str(pr.get("stdout", "")).strip()
    repo_url = f"https://{host}/{target}"
    if policy.get("enable_push_protection"):
        security = _run_capture([
            "gh", "repo", "edit", target,
            "--enable-secret-scanning", "--enable-secret-scanning-push-protection",
        ], remote_work, timeout=60, env=env)
        actions.append(security)
    result = {
        "publication_id": publication_id,
        "status": "published-pr" if pr_url else "published",
        "repository": target,
        "repository_url": repo_url,
        "pull_request_url": pr_url,
        "branch": branch,
        "published_at": now(),
        "manifest_sha256": manifest_sha,
        "restart_or_merge_required": bool(pr_url),
    }
    update_publication(publication_id, **{k: v for k, v in result.items() if k != "publication_id"})
    append_jsonl(PUBLISH_HISTORY, {"action": "published", **result})
    atomic_json(session / "PUBLISH_RESULT.json", {**result, "actions": actions})
    return result


def enqueue_publication_after_improvement(improvement_id: str) -> dict[str, Any]:
    policy = github_publish_policy()
    mode = policy.get("after_verified", "notify")
    if not policy.get("enabled") or mode == "off":
        return {"status": "disabled"}
    for item in folded_publications():
        if item.get("improvement_id") == improvement_id and item.get("status") not in {"aborted", "failed"}:
            return item
    if mode == "prepare" and _publish_target(policy) and policy.get("visibility"):
        prepared = _prepare_publication(improvement_id=improvement_id)
        _scan_public_snapshot(prepared["publication_id"])
        return get_publication(prepared["publication_id"])
    publication_id = f"PUB-{local_stamp()}-{uuid.uuid4().hex[:6]}"
    record = {
        "action": "opened", "publication_id": publication_id, "created_at": now(), "updated_at": now(),
        "system_version": SYSTEM_VERSION, "improvement_id": improvement_id, "status": "awaiting-configuration",
        "target": _publish_target(policy), "visibility": policy.get("visibility", ""),
        "message": "自我迭代已通过真实场景验证，可准备开源发布。",
    }
    append_jsonl(PUBLISH_QUEUE, record)
    append_jsonl(PUBLISH_HISTORY, record)
    return record


def cmd_publish_policy_show(args: argparse.Namespace) -> int:
    policy = github_publish_policy()
    payload = dict(policy)
    payload["target"] = _publish_target(policy)
    payload["auth"] = _github_auth_status(policy)
    payload["token_configured"] = bool(os.environ.get(str(policy.get("token_env", "GITHUB_PUBLISH_TOKEN"))))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _prompt_value(label: str, current: str = "", choices: list[str] | None = None, required: bool = True) -> str:
    if not sys.stdin.isatty():
        if required and not current:
            raise ReproError(f"缺少 {label}；请通过命令参数提供，或在交互式终端运行 publish configure")
        return current
    suffix = f" [{current}]" if current else ""
    if choices:
        suffix += f" ({'/'.join(choices)})"
    while True:
        value = input(f"{label}{suffix}: ").strip() or current
        if choices and value not in choices:
            print(f"请选择：{', '.join(choices)}")
            continue
        if required and not value:
            print("该项不能为空")
            continue
        return value


def cmd_publish_configure(args: argparse.Namespace) -> int:
    policy = github_publish_policy()
    policy["host"] = args.host or policy.get("host") or "github.com"
    policy["owner"] = args.owner or policy.get("owner") or ""
    policy["repository"] = args.repository or policy.get("repository") or ""
    policy["visibility"] = args.visibility or policy.get("visibility") or ""
    policy["description"] = args.description if args.description is not None else policy.get("description", "")
    policy["license"] = args.license or policy.get("license") or "MIT"
    policy["copyright_holder"] = args.copyright_holder if args.copyright_holder is not None else policy.get("copyright_holder", "")
    policy["auth_method"] = args.auth_method or policy.get("auth_method") or "gh"
    policy["token_env"] = args.token_env or policy.get("token_env") or "GITHUB_PUBLISH_TOKEN"
    policy["existing_repo_mode"] = args.existing_repo_mode or policy.get("existing_repo_mode") or "pull-request"
    policy["sync_mode"] = args.sync_mode or policy.get("sync_mode") or "managed-mirror"
    policy["after_verified"] = args.after_verified or policy.get("after_verified") or "notify"
    policy["git_author_name"] = args.git_author_name if args.git_author_name is not None else policy.get("git_author_name", "")
    policy["git_author_email"] = args.git_author_email if args.git_author_email is not None else policy.get("git_author_email", "")
    if args.interactive or (not policy["owner"] or not policy["repository"] or not policy["visibility"]):
        policy["owner"] = _prompt_value("GitHub 用户名或组织名", str(policy.get("owner", "")))
        policy["repository"] = _prompt_value("目标仓库名", str(policy.get("repository", "")) or "opencode-paper-repro")
        policy["visibility"] = _prompt_value("仓库可见性", str(policy.get("visibility", "")) or "private", ["private", "public", "internal"])
        policy["description"] = _prompt_value("仓库简介", str(policy.get("description", "")), required=False)
        policy["license"] = _prompt_value("许可证", str(policy.get("license", "MIT")), ["MIT", "none"])
        if policy["license"] == "MIT":
            policy["copyright_holder"] = _prompt_value("MIT 版权归属名称（将公开）", str(policy.get("copyright_holder", "")) or str(policy["owner"]))
        policy["auth_method"] = _prompt_value("认证方式", str(policy.get("auth_method", "gh")), ["gh", "token"])
        policy["existing_repo_mode"] = _prompt_value("已有仓库更新方式", str(policy.get("existing_repo_mode", "pull-request")), ["pull-request", "direct"])
        policy["sync_mode"] = _prompt_value("已有仓库文件同步方式", str(policy.get("sync_mode", "managed-mirror")), ["managed-mirror", "preserve-extra"])
        policy["after_verified"] = _prompt_value("自我迭代验证后", str(policy.get("after_verified", "notify")), ["off", "notify", "prepare"])
    if policy["visibility"] not in PUBLISH_VISIBILITIES:
        raise ReproError("visibility 必须是 public/private/internal")
    owner = str(policy.get("owner", ""))
    repository = str(policy.get("repository", ""))
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", owner):
        raise ReproError("GitHub owner 格式无效；请填写用户名或组织名，不要包含 URL 或斜杠")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", repository) or repository in {".", ".."}:
        raise ReproError("GitHub 仓库名格式无效")
    if str(policy.get("license", "MIT")) not in {"MIT", "none"}:
        raise ReproError("当前自动生成支持 MIT 或 none；其他许可证请在隔离快照中人工提供 LICENSE 后重新扫描")
    save_github_publish_policy(policy)
    payload = dict(policy)
    payload["target"] = _publish_target(policy)
    payload["next"] = "paper-repro publish auth status"
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_publish_auth_status(args: argparse.Namespace) -> int:
    print(json.dumps(_github_auth_status(github_publish_policy()), ensure_ascii=False, indent=2))
    return 0


def cmd_publish_list(args: argparse.Namespace) -> int:
    items = folded_publications()
    if args.status:
        items = [item for item in items if item.get("status") == args.status]
    print(json.dumps(items, ensure_ascii=False, indent=2))
    return 0


def cmd_publish_prepare(args: argparse.Namespace) -> int:
    result = _prepare_publication(improvement_id=args.improvement_id or "", force=args.force)
    if args.scan:
        result["scan"] = _scan_public_snapshot(result["publication_id"])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_publish_scan(args: argparse.Namespace) -> int:
    print(json.dumps(_scan_public_snapshot(args.publication_id), ensure_ascii=False, indent=2))
    return 0


def cmd_publish_review(args: argparse.Namespace) -> int:
    session = publication_session(args.publication_id)
    scan = read_json(session / "PRIVACY_SCAN.json", {}) or {}
    item = get_publication(args.publication_id)
    payload = {"publication": item, "scan": scan, "review": str(session / "REVIEW.md") if (session / "REVIEW.md").exists() else ""}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_publish_approve(args: argparse.Namespace) -> int:
    policy = github_publish_policy()
    target = _publish_target(policy)
    if not target or not policy.get("visibility"):
        raise ReproError("请先配置 GitHub owner/repository/visibility")
    scan = read_json(publication_session(args.publication_id) / "PRIVACY_SCAN.json", {}) or {}
    if not scan.get("passed"):
        raise ReproError("隐私扫描未通过，不能批准")
    warnings = scan.get("warnings", []) or []
    if warnings and not args.ack_warnings:
        raise ReproError("隐私扫描存在人工复核警告；请先 review，确认后使用 --ack-warnings 批准")
    expected_phrase = f"PUBLISH {target} AS {policy['visibility']}"
    confirm = args.confirm or ""
    if not confirm and sys.stdin.isatty():
        print(f"即将向外部 GitHub 仓库发布系统源码。不会上传项目工作区、论文、日志或统一配置。\n请输入以下完整短语确认：\n{expected_phrase}")
        confirm = input("> ").strip()
    if confirm != expected_phrase:
        raise ReproError("确认短语不匹配，未批准发布")
    manifest_sha = str(scan.get("manifest", {}).get("manifest_sha256", ""))
    ttl = int(policy.get("approval_ttl_seconds", 3600))
    approval = {
        "publication_id": args.publication_id,
        "approved_at": now(),
        "expires_epoch": time.time() + ttl,
        "target": target,
        "visibility": policy["visibility"],
        "manifest_sha256": manifest_sha,
        "policy_fingerprint": _publication_policy_fingerprint(policy),
        "warnings_acknowledged": bool(args.ack_warnings or not warnings),
        "confirmation_fingerprint": hashlib.sha256(confirm.encode("utf-8")).hexdigest()[:16],
    }
    atomic_json(_approval_file(args.publication_id), approval)
    update_publication(args.publication_id, status="approved", approved_at=approval["approved_at"], approval_expires_epoch=approval["expires_epoch"])
    print(json.dumps({**approval, "next": f"paper-repro publish push {args.publication_id}"}, ensure_ascii=False, indent=2))
    return 0


def cmd_publish_push(args: argparse.Namespace) -> int:
    print(json.dumps(_publish_to_github(args.publication_id), ensure_ascii=False, indent=2))
    return 0


def cmd_publish_abort(args: argparse.Namespace) -> int:
    update_publication(args.publication_id, status="aborted", aborted_at=now(), reason=args.reason)
    if args.delete_session:
        shutil.rmtree(publication_session(args.publication_id), ignore_errors=True)
    print(json.dumps({"publication_id": args.publication_id, "status": "aborted"}, ensure_ascii=False, indent=2))
    return 0


def cmd_publish_purge(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ReproError("删除本地发布会话需要显式 --yes")
    removed = []
    if PUBLISH_HOME.exists():
        shutil.rmtree(PUBLISH_HOME)
        removed.append(str(PUBLISH_HOME))
    print(json.dumps({
        "purged": True,
        "removed": removed,
        "remote_repository_unchanged": True,
        "note": "只删除本地发布队列、快照、扫描报告和历史；不会删除 GitHub 仓库。",
    }, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenCode paper reproduction controller")
    parser.add_argument("--version", action="version", version=f"%(prog)s {SYSTEM_VERSION}")
    add_common_options(parser)
    sub = parser.add_subparsers(dest="cmd", required=True)

    command = sub.add_parser("init", help="Create a new run")
    command.add_argument("--repository", default="")
    command.add_argument("--paper", default="")
    command.set_defaults(func=cmd_init)

    command = sub.add_parser("exec", help="Execute a logged command")
    command.add_argument("--stage", required=True)
    command.add_argument("--command", required=True)
    command.add_argument("--timeout", type=int, default=86400)
    command.add_argument("--estimate", type=int, default=0)
    command.add_argument("--secret-env", action="append", default=[], help="Task-scoped secret env; must be explicitly authorized by workspace security policy")
    command.set_defaults(func=cmd_exec)

    command = sub.add_parser("download", help="Download a large HTTP(S) asset with resume, progress, speed and ETA")
    command.add_argument("--url", required=True)
    command.add_argument("--output", required=True)
    command.add_argument("--stage", default="assets")
    command.add_argument("--kind", default="download")
    command.add_argument("--sha256", default="")
    command.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    command.add_argument("--chunk-size", type=int, default=1024 * 1024)
    command.add_argument("--read-timeout", type=int, default=120)
    command.set_defaults(func=cmd_download)

    command = sub.add_parser("register", help="Register an artifact")
    command.add_argument("--path", required=True)
    command.add_argument("--kind", required=True)
    command.add_argument("--source", default="")
    command.add_argument("--revision", default="")
    command.set_defaults(func=cmd_register)

    command = sub.add_parser("status", help="Show run status")
    command.add_argument("--json", action="store_true")
    command.add_argument("--watch", action="store_true")
    command.add_argument("--interval", type=float, default=3.0)
    command.set_defaults(func=cmd_status)


    gpu = sub.add_parser("gpu", help="Inspect and confirm the GPU pool available to this reproduction run")
    gpu_sub = gpu.add_subparsers(dest="gpu_cmd", required=True)
    gpu_prepare = gpu_sub.add_parser("prepare", help="Return detected GPUs and whether this run needs user confirmation")
    gpu_prepare.add_argument("--json", action="store_true")
    gpu_prepare.set_defaults(func=cmd_gpu_prepare)
    gpu_inspect = gpu_sub.add_parser("inspect", help="Show raw GPU telemetry plus paper-repro assignment state")
    gpu_inspect.add_argument("--json", action="store_true")
    gpu_inspect.set_defaults(func=cmd_gpu_inspect)
    gpu_show = gpu_sub.add_parser("show", help="Show run GPU policy, workspace defaults and telemetry")
    gpu_show.set_defaults(func=cmd_gpu_show)
    gpu_configure = gpu_sub.add_parser("configure", help="Confirm which physical GPUs paper-repro may schedule for this run")
    gpu_configure.add_argument("--ids", default="", help="Comma-separated physical GPU IDs, or none for CPU-only")
    gpu_configure.add_argument("--interactive", action="store_true")
    gpu_configure.add_argument("--remember-workspace", action="store_true", help="Remember the selection as the suggestion for future runs; each run still confirms")
    gpu_configure.add_argument("--max-parallel", type=int)
    gpu_configure.add_argument("--cpu-parallel", type=int, default=1)
    gpu_configure.add_argument("--external-busy-memory-mb", type=int)
    gpu_configure.add_argument("--external-busy-util-pct", type=int)
    gpu_configure.add_argument("--allow-external-busy", action="store_true", help="Allow scheduling onto GPUs that appear busy from external workloads")
    gpu_configure.add_argument("--allow-missing", action="store_true", help="Record IDs that are not currently visible (advanced/debug only)")
    gpu_configure.set_defaults(func=cmd_gpu_configure)

    runtime = sub.add_parser("runtime", help="Persistent task registry, execution plans, progress, ETA and machine-readable runtime state")
    runtime_sub = runtime.add_subparsers(dest="runtime_cmd", required=True)
    rt_submit = runtime_sub.add_parser("submit", help="Submit one task to the persistent scheduler and return immediately")
    rt_submit.add_argument("--name", required=True)
    rt_submit.add_argument("--stage", default="execution")
    rt_submit.add_argument("--command", required=True)
    rt_submit.add_argument("--timeout", type=int, default=86400)
    rt_submit.add_argument("--estimate", type=int, default=0)
    rt_submit.add_argument("--gpu-count", type=int, required=True, help="0 for CPU, 1 for single GPU, N for a multi-GPU job")
    rt_submit.add_argument("--gpu-ids", default="", help="Optional preferred physical GPU IDs")
    rt_submit.add_argument("--min-free-memory-mb", type=int, default=0)
    rt_submit.add_argument("--priority", type=int, default=0)
    rt_submit.add_argument("--depends-on", action="append", default=[], help="Task ID dependency; repeatable")
    rt_submit.add_argument("--parallel-group", default="")
    rt_submit.add_argument("--progress-adapter", default='{"type":"auto"}', help="JSON: auto/native/tqdm/jsonl-line-count/line-count/file-count/regex-log")
    rt_submit.add_argument("--output", action="append", default=[])
    rt_submit.add_argument("--secret-env", action="append", default=[], help="Task-scoped secret env; must be explicitly authorized by workspace security policy")
    rt_submit.add_argument("--start-scheduler", action=argparse.BooleanOptionalAction, default=True)
    rt_submit.set_defaults(func=cmd_runtime_submit)
    rt_status = runtime_sub.add_parser("status", help="Stable machine-readable runtime status")
    rt_status.add_argument("--json", action="store_true")
    rt_status.set_defaults(func=cmd_runtime_status)
    rt_tasks = runtime_sub.add_parser("tasks", help="List registered tasks")
    rt_tasks.add_argument("--active", action="store_true")
    rt_tasks.add_argument("--pending", action="store_true")
    rt_tasks.add_argument("--json", action="store_true")
    rt_tasks.set_defaults(func=cmd_runtime_tasks)
    rt_task = runtime_sub.add_parser("task", help="Show one registered task")
    rt_task.add_argument("task_id")
    rt_task.add_argument("--json", action="store_true")
    rt_task.set_defaults(func=cmd_runtime_task)
    rt_gpu = runtime_sub.add_parser("gpu", help="Show GPU to task mapping")
    rt_gpu.add_argument("--json", action="store_true")
    rt_gpu.set_defaults(func=cmd_runtime_gpu)
    rt_events = runtime_sub.add_parser("events", help="Read incremental runtime events")
    rt_events.add_argument("--after", default="")
    rt_events.add_argument("--limit", type=int, default=500)
    rt_events.add_argument("--json", action="store_true")
    rt_events.set_defaults(func=cmd_runtime_events)
    rt_cancel = runtime_sub.add_parser("cancel", help="Cancel a queued/running task")
    rt_cancel.add_argument("task_id")
    rt_cancel.set_defaults(func=cmd_runtime_cancel)
    rt_retry = runtime_sub.add_parser("retry", help="Requeue a terminal task")
    rt_retry.add_argument("task_id")
    rt_retry.set_defaults(func=cmd_runtime_retry)
    rt_plan = runtime_sub.add_parser("plan", help="Create/show/submit a multi-task execution plan")
    rt_plan_sub = rt_plan.add_subparsers(dest="runtime_plan_cmd", required=True)
    rt_plan_save = rt_plan_sub.add_parser("save")
    rt_plan_save.add_argument("--file", default="")
    rt_plan_save.add_argument("--tasks-json", default="")
    rt_plan_save.set_defaults(func=cmd_runtime_plan_save)
    rt_plan_show = rt_plan_sub.add_parser("show")
    rt_plan_show.set_defaults(func=cmd_runtime_plan_show)
    rt_plan_submit = rt_plan_sub.add_parser("submit")
    rt_plan_submit.add_argument("--file", default="")
    rt_plan_submit.add_argument("--tasks-json", default="")
    rt_plan_submit.set_defaults(func=cmd_runtime_plan_submit)

    scheduler = sub.add_parser("scheduler", help="Persistent queue scheduler independent from the OpenCode agent session")
    scheduler_sub = scheduler.add_subparsers(dest="scheduler_cmd", required=True)
    scheduler_start = scheduler_sub.add_parser("start")
    scheduler_start.set_defaults(func=cmd_scheduler_start)
    scheduler_status = scheduler_sub.add_parser("status")
    scheduler_status.set_defaults(func=cmd_scheduler_status)
    scheduler_stop = scheduler_sub.add_parser("stop")
    scheduler_stop.set_defaults(func=cmd_scheduler_stop)
    scheduler_serve = scheduler_sub.add_parser("serve", help=argparse.SUPPRESS)
    scheduler_serve.set_defaults(func=cmd_scheduler_serve)
    scheduler_worker = scheduler_sub.add_parser("task-worker", help=argparse.SUPPRESS)
    scheduler_worker.add_argument("task_id")
    scheduler_worker.set_defaults(func=cmd_scheduler_task_worker)

    remote = sub.add_parser("remote", help="Stable JSON contract for Remote Bridge / WorkBuddy and other remote clients")
    remote_sub = remote.add_subparsers(dest="remote_cmd", required=True)
    remote_capabilities = remote_sub.add_parser("capabilities", help="Feature handshake for remote clients; do not infer features from version strings")
    remote_capabilities.add_argument("--json", action="store_true")
    remote_capabilities.set_defaults(func=cmd_remote_capabilities)
    remote_discover = remote_sub.add_parser("discover", help="List registered workspaces/runs for remote clients")
    remote_discover.add_argument("--active", action="store_true", help="Show only active/waiting runs")
    remote_discover.add_argument("--json", action="store_true")
    remote_discover.set_defaults(func=cmd_remote_discover)
    remote_snapshot = remote_sub.add_parser("snapshot")
    remote_snapshot.add_argument("--json", action="store_true")
    remote_snapshot.add_argument("--include-command", action="store_true", help="Include task command/cwd; safe mode omits them")
    remote_snapshot.add_argument("--include-telemetry", action="store_true", help="Include nvidia-smi-style raw telemetry; Bridge normally collects telemetry itself")
    remote_snapshot.set_defaults(func=cmd_remote_snapshot)
    remote_events = remote_sub.add_parser("events")
    remote_events.add_argument("--after", default="")
    remote_events.add_argument("--limit", type=int, default=500)
    remote_events.add_argument("--json", action="store_true")
    remote_events.set_defaults(func=cmd_remote_events)
    remote_decisions = remote_sub.add_parser("decisions")
    remote_decisions.add_argument("--json", action="store_true")
    remote_decisions.set_defaults(func=cmd_remote_decisions)
    remote_decide = remote_sub.add_parser("decide")
    remote_decide.add_argument("decision_id")
    remote_decide.add_argument("option")
    remote_decide.add_argument("--remember", choices=["none", "workspace", "global"], default="none")
    remote_decide.add_argument("--note", default="")
    remote_decide.add_argument("--json", action="store_true")
    remote_decide.set_defaults(func=cmd_remote_decide)

    remote_session = remote_sub.add_parser("session", help="Optional OpenCode session/directory hint; Bridge still feature-detects and selects the live session")
    remote_session_sub = remote_session.add_subparsers(dest="remote_session_cmd", required=True)
    remote_session_show = remote_session_sub.add_parser("show")
    remote_session_show.add_argument("--json", action="store_true")
    remote_session_show.set_defaults(func=cmd_remote_session_show)
    remote_session_bind = remote_session_sub.add_parser("bind")
    remote_session_bind.add_argument("--session-id", default="")
    remote_session_bind.add_argument("--directory", default="")
    remote_session_bind.add_argument("--source", default="remote-bridge")
    remote_session_bind.add_argument("--json", action="store_true")
    remote_session_bind.set_defaults(func=cmd_remote_session_bind)
    remote_session_clear = remote_session_sub.add_parser("clear")
    remote_session_clear.add_argument("--json", action="store_true")
    remote_session_clear.set_defaults(func=cmd_remote_session_clear)

    remote_command = remote_sub.add_parser("command", help="Audit metadata for Bridge -> OpenCode writes; paper-repro does not dispatch OpenCode HTTP")
    remote_command_sub = remote_command.add_subparsers(dest="remote_command_cmd", required=True)
    remote_command_record = remote_command_sub.add_parser("record")
    remote_command_record.add_argument("--request-id", required=True)
    remote_command_record.add_argument("--target", choices=["opencode", "paper-repro"], default="opencode")
    remote_command_record.add_argument("--type", dest="command_type", choices=["prompt", "slash-command", "permission", "question", "decision", "diagnostic"], required=True)
    remote_command_record.add_argument("--session-id", default="")
    remote_command_record.add_argument("--state", choices=["queued", "dispatched", "accepted", "completed", "failed", "expired", "cancelled"], required=True)
    remote_command_record.add_argument("--requires-idle", action="store_true")
    remote_command_record.add_argument("--priority", choices=["low", "normal", "high"], default="normal")
    remote_command_record.add_argument("--ttl-seconds", type=int, default=3600)
    remote_command_record.add_argument("--idempotency-key", default="")
    remote_command_record.add_argument("--summary", default="", help="Redacted human-readable summary only; do not pass secrets/full prompts")
    remote_command_record.add_argument("--payload-sha256", default="", help="Optional hash of the Bridge payload for audit/correlation")
    remote_command_record.add_argument("--json", action="store_true")
    remote_command_record.set_defaults(func=cmd_remote_command_record)
    remote_command_list = remote_command_sub.add_parser("list")
    remote_command_list.add_argument("--state", choices=["queued", "dispatched", "accepted", "completed", "failed", "expired", "cancelled"], default="")
    remote_command_list.add_argument("--limit", type=int, default=100)
    remote_command_list.add_argument("--json", action="store_true")
    remote_command_list.set_defaults(func=cmd_remote_command_list)

    command = sub.add_parser("stage", help="Update structured stage state")
    command.add_argument("--stage", required=True)
    command.add_argument("--status", default="running")
    command.add_argument("--progress", type=float)
    command.add_argument("--message", default="")
    command.add_argument("--eta", type=int)
    command.add_argument("--step", type=int, help="Current pipeline step index, e.g. 4")
    command.add_argument("--step-total", type=int, help="Total number of pipeline steps")
    command.add_argument("--step-name", default="", help="Human-readable step name")
    command.add_argument("--step-status", choices=["pending", "running", "completed", "failed", "blocked"])
    command.set_defaults(func=cmd_stage)

    security = sub.add_parser("security", help="Inspect and configure execution security boundaries")
    security_sub = security.add_subparsers(dest="security_cmd", required=True)
    sec_show = security_sub.add_parser("show")
    sec_show.set_defaults(func=cmd_security_show)
    sec_sandbox = security_sub.add_parser("sandbox")
    sec_sandbox_sub = sec_sandbox.add_subparsers(dest="security_sandbox_cmd", required=True)
    sec_sandbox_set = sec_sandbox_sub.add_parser("set")
    sec_sandbox_set.add_argument("--mode", choices=["auto", "required", "trusted-off"], required=True)
    sec_sandbox_set.add_argument("--network", choices=["on", "off"], default="on")
    sec_sandbox_set.add_argument("--yes", action="store_true")
    sec_sandbox_set.set_defaults(func=cmd_security_sandbox_set)
    sec_secret = security_sub.add_parser("secret")
    sec_secret_sub = sec_secret.add_subparsers(dest="security_secret_cmd", required=True)
    sec_secret_allow = sec_secret_sub.add_parser("allow")
    sec_secret_allow.add_argument("name")
    sec_secret_allow.add_argument("--yes", action="store_true")
    sec_secret_allow.set_defaults(func=cmd_security_secret_allow)
    sec_secret_revoke = sec_secret_sub.add_parser("revoke")
    sec_secret_revoke.add_argument("name")
    sec_secret_revoke.set_defaults(func=cmd_security_secret_revoke)
    sec_root = security_sub.add_parser("download-root")
    sec_root_sub = sec_root.add_subparsers(dest="security_root_cmd", required=True)
    sec_root_add = sec_root_sub.add_parser("add")
    sec_root_add.add_argument("path")
    sec_root_add.add_argument("--yes", action="store_true")
    sec_root_add.set_defaults(func=cmd_security_download_root_add)
    sec_root_remove = sec_root_sub.add_parser("remove")
    sec_root_remove.add_argument("path")
    sec_root_remove.set_defaults(func=cmd_security_download_root_remove)
    sec_perms = security_sub.add_parser("permissions")
    sec_perms_sub = sec_perms.add_subparsers(dest="security_permissions_cmd", required=True)
    sec_perms_repair = sec_perms_sub.add_parser("repair")
    sec_perms_repair.add_argument("--scope", choices=["workspace", "global", "all"], default="workspace")
    sec_perms_repair.add_argument("--yes", action="store_true")
    sec_perms_repair.set_defaults(func=cmd_security_permissions_repair)

    env = sub.add_parser("env", help="Create, select and inspect the per-project Conda execution environment")
    env_sub = env.add_subparsers(dest="env_cmd", required=True)
    env_show = env_sub.add_parser("show")
    env_show.set_defaults(func=cmd_env_show)
    env_use = env_sub.add_parser("use")
    env_selector = env_use.add_mutually_exclusive_group(required=True)
    env_selector.add_argument("--name")
    env_selector.add_argument("--prefix")
    env_use.add_argument("--no-enforce", action="store_true", help="Record the environment without strict enforcement")
    env_use.set_defaults(func=cmd_env_use)
    env_create = env_sub.add_parser("create")
    create_selector = env_create.add_mutually_exclusive_group(required=True)
    create_selector.add_argument("--name")
    create_selector.add_argument("--prefix")
    env_create.add_argument("--python", default="3.11")
    env_create.add_argument("--package", action="append", default=[], help="Additional package for conda create; repeatable")
    env_create.set_defaults(func=cmd_env_create)
    env_clear = env_sub.add_parser("clear")
    env_clear.set_defaults(func=cmd_env_clear)

    models = sub.add_parser("models", help="Configure capability-based model routing without hard-coded providers or model names")
    models_sub = models.add_subparsers(dest="models_cmd", required=True)
    models_show = models_sub.add_parser("show")
    models_show.set_defaults(func=cmd_models_show)
    models_native = models_sub.add_parser("native")
    models_native.add_argument("--capability", choices=["auto", "vision", "text-only"], default="auto")
    models_native.add_argument("--scope", choices=["global", "workspace"], default="global")
    models_native.set_defaults(func=cmd_models_native)
    profile = models_sub.add_parser("profile")
    profile_sub = profile.add_subparsers(dest="profile_cmd", required=True)
    profile_set = profile_sub.add_parser("set")
    profile_set.add_argument("--name", required=True)
    profile_set.add_argument("--protocol", choices=["openai-compatible"], default="openai-compatible")
    profile_set.add_argument("--base-url", required=True)
    profile_set.add_argument("--model", required=True)
    profile_set.add_argument("--api-key-env", required=True)
    profile_set.add_argument("--capabilities", default="vision,document,ocr,table,chart,formula")
    profile_set.add_argument("--max-tokens", type=int, default=8192)
    profile_set.add_argument("--temperature", type=float, default=0.0)
    profile_set.add_argument("--scope", choices=["global", "workspace"], default="global")
    profile_set.set_defaults(func=cmd_models_profile_set)
    profile_remove = profile_sub.add_parser("remove")
    profile_remove.add_argument("--name", required=True)
    profile_remove.add_argument("--scope", choices=["global", "workspace"], default="global")
    profile_remove.set_defaults(func=cmd_models_profile_remove)
    models_route = models_sub.add_parser("route")
    models_route.add_argument("--task", choices=["vision", "document", "ocr", "table", "chart", "formula"], required=True)
    models_route.add_argument("--profile", action="append", required=True, help="Fallback profile in priority order; repeatable")
    models_route.add_argument("--scope", choices=["global", "workspace"], default="global")
    models_route.set_defaults(func=cmd_models_route)

    vision = sub.add_parser("vision", help="Call configured fallback vision profiles after native vision is unavailable")
    vision_sub = vision.add_subparsers(dest="vision_cmd", required=True)
    for action, handler in [("analyze", cmd_vision_analyze), ("test", cmd_vision_test)]:
        vision_cmd = vision_sub.add_parser(action)
        vision_cmd.add_argument("--input", action="append", required=True, help="Image or PDF path; repeatable")
        vision_cmd.add_argument("--pages", default="1", help="1-based PDF page selection, e.g. 1,3-5")
        vision_cmd.add_argument("--dpi", type=int, default=180)
        vision_cmd.add_argument("--task", choices=["vision", "document", "ocr", "table", "chart", "formula"], default="vision")
        vision_cmd.add_argument("--prompt", default="")
        vision_cmd.add_argument("--profile", default="", help="Force one configured fallback profile")
        vision_cmd.add_argument("--native-result", default="", help="Record a result produced natively by the active base model")
        vision_cmd.add_argument("--output", default="")
        vision_cmd.add_argument("--timeout", type=int, default=300)
        vision_cmd.set_defaults(func=handler)

    paper = sub.add_parser("paper", help="Inspect PDF text/visual structure and configure hybrid paper-audit policy")
    paper_sub = paper.add_subparsers(dest="paper_cmd", required=True)
    paper_policy = paper_sub.add_parser("policy")
    paper_policy_sub = paper_policy.add_subparsers(dest="paper_policy_cmd", required=True)
    paper_policy_show = paper_policy_sub.add_parser("show")
    paper_policy_show.set_defaults(func=cmd_paper_policy_show)
    paper_policy_set = paper_policy_sub.add_parser("set")
    paper_policy_set.add_argument("--vision-policy", choices=["targeted", "on-demand", "all-pages", "off"])
    paper_policy_set.add_argument("--verify-tables", action=argparse.BooleanOptionalAction, default=None)
    paper_policy_set.add_argument("--verify-method-figures", action=argparse.BooleanOptionalAction, default=None)
    paper_policy_set.add_argument("--max-vision-pages", type=int)
    paper_policy_set.add_argument("--dpi", type=int)
    paper_policy_set.set_defaults(func=cmd_paper_policy_set)
    paper_inspect = paper_sub.add_parser("inspect")
    paper_inspect.add_argument("--input", required=True)
    paper_inspect.add_argument("--vision-policy", choices=["targeted", "on-demand", "all-pages", "off"])
    paper_inspect.add_argument("--low-text-threshold", type=int, default=120)
    paper_inspect.set_defaults(func=cmd_paper_inspect)

    code = sub.add_parser("code", help="Build and inspect a static code index used by the code-explainer agent")
    code_sub = code.add_subparsers(dest="code_cmd", required=True)
    code_index = code_sub.add_parser("index")
    code_index.set_defaults(func=cmd_code_index)
    code_show = code_sub.add_parser("show")
    code_show.set_defaults(func=cmd_code_show)

    decisions = sub.add_parser("decisions", help="Manage adaptive human-in-the-loop decisions and interruption budgets")
    decisions_sub = decisions.add_subparsers(dest="decisions_cmd", required=True)
    decisions_policy = decisions_sub.add_parser("policy")
    decisions_policy_sub = decisions_policy.add_subparsers(dest="decisions_policy_cmd", required=True)
    decisions_policy_show = decisions_policy_sub.add_parser("show")
    decisions_policy_show.set_defaults(func=cmd_decisions_policy_show)
    decisions_policy_set = decisions_policy_sub.add_parser("set")
    decisions_policy_set.add_argument("--scope", choices=["global", "workspace"], default="workspace")
    decisions_policy_set.add_argument("--mode", choices=list(DECISION_MODES))
    decisions_policy_set.add_argument("--max-interruptions-per-stage", type=int)
    decisions_policy_set.add_argument("--max-interruptions-per-run", type=int)
    decisions_policy_set.add_argument("--max-decisions-per-checkpoint", type=int)
    decisions_policy_set.add_argument("--batch-related-decisions", action=argparse.BooleanOptionalAction, default=None)
    decisions_policy_set.add_argument("--use-remembered-preferences", action=argparse.BooleanOptionalAction, default=None)
    decisions_policy_set.set_defaults(func=cmd_decisions_policy_set)

    decisions_assess = decisions_sub.add_parser("assess", help="Classify a material choice and decide whether user confirmation is required")
    decisions_assess.add_argument("--title", required=True)
    decisions_assess.add_argument("--question", required=True)
    decisions_assess.add_argument("--category", default="routine")
    decisions_assess.add_argument("--stage", default="")
    decisions_assess.add_argument("--impact", choices=["low", "medium", "high", "critical"], default="medium")
    decisions_assess.add_argument("--reversibility", choices=["reversible", "partial", "irreversible"], default="reversible")
    decisions_assess.add_argument("--confidence", type=float, default=0.9)
    decisions_assess.add_argument("--changes-results", action="store_true")
    decisions_assess.add_argument("--external-side-effect", action="store_true")
    decisions_assess.add_argument("--estimated-hours", type=float, default=0.0)
    decisions_assess.add_argument("--estimated-cost-cny", type=float, default=0.0)
    decisions_assess.add_argument("--download-gb", type=float, default=0.0)
    decisions_assess.add_argument("--patch-files", type=int, default=0)
    decisions_assess.add_argument("--options-json", required=True)
    decisions_assess.add_argument("--default-option", default="")
    decisions_assess.add_argument("--recommended-option", default="")
    decisions_assess.add_argument("--preference-key", default="")
    decisions_assess.add_argument("--context", default="")
    decisions_assess.set_defaults(func=cmd_decisions_assess)

    decisions_list = decisions_sub.add_parser("list")
    decisions_list.add_argument("--pending", action="store_true")
    decisions_list.set_defaults(func=cmd_decisions_list)
    decisions_pending = decisions_sub.add_parser("pending", help="Stable JSON alias for pending decisions")
    decisions_pending.add_argument("--json", action="store_true")
    decisions_pending.set_defaults(func=cmd_decisions_list, pending=True)
    decisions_resolve = decisions_sub.add_parser("resolve")
    decisions_resolve.add_argument("decision_id")
    decisions_resolve.add_argument("--option", required=True)
    decisions_resolve.add_argument("--remember", choices=["none", "workspace", "global"], default="none")
    decisions_resolve.add_argument("--note", default="")
    decisions_resolve.add_argument("--json", action="store_true")
    decisions_resolve.set_defaults(func=cmd_decisions_resolve)
    decisions_checkpoint = decisions_sub.add_parser("checkpoint")
    decisions_checkpoint.add_argument("--stage", default="")
    decisions_checkpoint.set_defaults(func=cmd_decisions_checkpoint)

    secrets = sub.add_parser("secrets", help="Persist and manage model/MCP credentials in one protected file")
    secrets_sub = secrets.add_subparsers(dest="secrets_cmd", required=True)
    secrets_init = secrets_sub.add_parser("init")
    secrets_init.add_argument("--force", action="store_true")
    secrets_init.add_argument("--quiet", action="store_true")
    secrets_init.set_defaults(func=cmd_secrets_init)
    secrets_set = secrets_sub.add_parser("set")
    secrets_set.add_argument("name")
    secrets_set.add_argument("--value", help="Convenient but may remain in shell history; interactive input is safer")
    secrets_set.add_argument("--stdin", action="store_true", help="Read the value from standard input")
    secrets_set.add_argument("--allow-empty", action="store_true")
    secrets_set.set_defaults(func=cmd_secrets_set)
    secrets_unset = secrets_sub.add_parser("unset")
    secrets_unset.add_argument("name")
    secrets_unset.set_defaults(func=cmd_secrets_unset)
    secrets_list = secrets_sub.add_parser("list")
    secrets_list.set_defaults(func=cmd_secrets_list)
    secrets_import = secrets_sub.add_parser("import-env")
    secrets_import.add_argument("name", nargs="*")
    secrets_import.add_argument("--known", action="store_true", help="Import known vision and MCP variables that are currently set")
    secrets_import.set_defaults(func=cmd_secrets_import_env)
    secrets_edit = secrets_sub.add_parser("edit")
    secrets_edit.add_argument("--editor", default="")
    secrets_edit.set_defaults(func=cmd_secrets_edit)
    secrets_clear = secrets_sub.add_parser("clear")
    secrets_clear.add_argument("--yes", action="store_true")
    secrets_clear.set_defaults(func=cmd_secrets_clear)
    secrets_exec = secrets_sub.add_parser("exec", help="内部启动器：加载统一密钥后执行命令")
    secrets_exec.add_argument("command", nargs=argparse.REMAINDER)
    secrets_exec.set_defaults(func=cmd_secrets_exec)

    config = sub.add_parser("config", help="Inspect or reset paper-repro configuration without deleting runs")
    config_sub = config.add_subparsers(dest="config_cmd", required=True)
    config_show = config_sub.add_parser("show")
    config_show.set_defaults(func=cmd_config_show)
    config_reset = config_sub.add_parser("reset")
    config_reset.add_argument("--scope", choices=["global", "workspace", "all"], default="global")
    config_reset.add_argument("--yes", action="store_true")
    config_reset.set_defaults(func=cmd_config_reset)

    mcp = sub.add_parser("mcp", help="Install and manage the minimal paper-reproduction MCP capability pack")
    mcp_sub = mcp.add_subparsers(dest="mcp_cmd", required=True)
    mcp_install = mcp_sub.add_parser("install-basic", help="Install native web search and a small MCP baseline")
    mcp_install.add_argument("--github", action="store_true", help="Enable GitHub read-only MCP")
    mcp_install.add_argument("--huggingface", action="store_true", help="Enable Hugging Face official MCP")
    mcp_install.add_argument("--brave-search", action="store_true", help="Enable Brave Search fallback MCP")
    mcp_install.add_argument("--all-available", action="store_true", help="Enable all packaged MCP servers")
    mcp_install.add_argument("--no-context7", action="store_true")
    mcp_install.add_argument("--no-native-websearch", action="store_true")
    mcp_install.add_argument("--quiet", action="store_true")
    mcp_install.set_defaults(func=cmd_mcp_install_basic)
    mcp_status = mcp_sub.add_parser("status", help="Show MCP and native web capability status")
    mcp_status.set_defaults(func=cmd_mcp_status)
    mcp_sync = mcp_sub.add_parser("sync", help="Regenerate the OpenCode runtime MCP config")
    mcp_sync.add_argument("--quiet", action="store_true")
    mcp_sync.set_defaults(func=cmd_mcp_sync)
    mcp_enable = mcp_sub.add_parser("enable")
    mcp_enable.add_argument("name", choices=["native-websearch", *MCP_SERVER_ORDER])
    mcp_enable.set_defaults(func=cmd_mcp_enable)
    mcp_disable = mcp_sub.add_parser("disable")
    mcp_disable.add_argument("name", choices=["native-websearch", *MCP_SERVER_ORDER])
    mcp_disable.set_defaults(func=cmd_mcp_disable)
    mcp_recommend = mcp_sub.add_parser("recommend")
    mcp_recommend.set_defaults(func=cmd_mcp_recommend)

    improve = sub.add_parser("improve", help="Guarded OpenCode-driven self-improvement from system issues or explicit user requests")
    improve_sub = improve.add_subparsers(dest="improve_cmd", required=True)
    improve_policy = improve_sub.add_parser("policy")
    improve_policy_sub = improve_policy.add_subparsers(dest="improve_policy_cmd", required=True)
    improve_policy_show = improve_policy_sub.add_parser("show")
    improve_policy_show.set_defaults(func=cmd_improve_policy_show)
    improve_policy_set = improve_policy_sub.add_parser("set")
    improve_policy_set.add_argument("--mode", choices=list(SELF_IMPROVE_MODES))
    improve_policy_set.add_argument("--auto-enqueue-system-issues", action=argparse.BooleanOptionalAction, default=None)
    improve_policy_set.add_argument("--auto-apply-safe-patches", action=argparse.BooleanOptionalAction, default=None)
    improve_policy_set.add_argument("--require-smoke-tests", action=argparse.BooleanOptionalAction, default=None)
    improve_policy_set.add_argument("--max-attempts", type=int)
    improve_policy_set.add_argument("--max-changed-files", type=int)
    improve_policy_set.add_argument("--auto-apply-max-files", type=int)
    improve_policy_set.set_defaults(func=cmd_improve_policy_set)
    improve_submit = improve_sub.add_parser("submit")
    improve_submit.add_argument("--title")
    improve_submit.add_argument("--details")
    improve_submit.add_argument("--issue-id")
    improve_submit.add_argument("--source", choices=["user-request", "system-issue"], default="user-request")
    improve_submit.add_argument("--priority", choices=["low", "normal", "high", "critical"], default="normal")
    improve_submit.set_defaults(func=cmd_improve_submit)
    improve_scan = improve_sub.add_parser("scan")
    improve_scan.set_defaults(func=cmd_improve_scan)
    improve_list = improve_sub.add_parser("list")
    improve_list.add_argument("--status", default="")
    improve_list.set_defaults(func=cmd_improve_list)
    improve_prepare = improve_sub.add_parser("prepare")
    improve_prepare.add_argument("improvement_id")
    improve_prepare.add_argument("--force", action="store_true")
    improve_prepare.set_defaults(func=cmd_improve_prepare)
    improve_context = improve_sub.add_parser("context")
    improve_context.add_argument("improvement_id")
    improve_context.set_defaults(func=cmd_improve_context)
    improve_tree = improve_sub.add_parser("tree")
    improve_tree.add_argument("improvement_id")
    improve_tree.add_argument("--prefix", default="")
    improve_tree.add_argument("--limit", type=int, default=300)
    improve_tree.set_defaults(func=cmd_improve_tree)
    improve_search = improve_sub.add_parser("search")
    improve_search.add_argument("improvement_id")
    improve_search.add_argument("--pattern", required=True)
    improve_search.add_argument("--ignore-case", action="store_true")
    improve_search.add_argument("--limit", type=int, default=100)
    improve_search.set_defaults(func=cmd_improve_search)
    improve_read = improve_sub.add_parser("read")
    improve_read.add_argument("improvement_id")
    improve_read.add_argument("--path", required=True)
    improve_read.add_argument("--start", type=int, default=1)
    improve_read.add_argument("--end", type=int, default=0)
    improve_read.add_argument("--max-kb", type=int, default=512)
    improve_read.set_defaults(func=cmd_improve_read)
    improve_write = improve_sub.add_parser("write")
    improve_write.add_argument("improvement_id")
    improve_write.add_argument("--path", required=True)
    improve_write.add_argument("--content")
    improve_write.add_argument("--content-base64")
    improve_write.add_argument("--stdin", action="store_true")
    improve_write.add_argument("--max-kb", type=int, default=1024)
    improve_write.set_defaults(func=cmd_improve_write)
    improve_test = improve_sub.add_parser("test")
    improve_test.add_argument("improvement_id")
    improve_test.set_defaults(func=cmd_improve_test)
    improve_diff = improve_sub.add_parser("diff")
    improve_diff.add_argument("improvement_id")
    improve_diff.add_argument("--summary", action="store_true")
    improve_diff.set_defaults(func=cmd_improve_diff)
    improve_propose = improve_sub.add_parser("propose")
    improve_propose.add_argument("improvement_id")
    improve_propose.set_defaults(func=cmd_improve_propose)
    improve_auto = improve_sub.add_parser("auto")
    improve_auto.add_argument("improvement_id")
    improve_auto.set_defaults(func=cmd_improve_auto)
    improve_apply = improve_sub.add_parser("apply")
    improve_apply.add_argument("improvement_id")
    improve_apply.add_argument("--yes", action="store_true")
    improve_apply.set_defaults(func=cmd_improve_apply)
    improve_verify = improve_sub.add_parser("verify")
    improve_verify.add_argument("improvement_id")
    verify_group = improve_verify.add_mutually_exclusive_group(required=True)
    verify_group.add_argument("--passed", action="store_true")
    verify_group.add_argument("--failed", dest="passed", action="store_false")
    improve_verify.add_argument("--note", default="")
    improve_verify.set_defaults(func=cmd_improve_verify)
    improve_discard = improve_sub.add_parser("discard")
    improve_discard.add_argument("improvement_id")
    improve_discard.add_argument("--reason", default="")
    improve_discard.add_argument("--delete-session", action="store_true")
    improve_discard.set_defaults(func=cmd_improve_discard)
    improve_rollback = improve_sub.add_parser("rollback")
    improve_rollback.add_argument("improvement_id")
    improve_rollback.add_argument("--yes", action="store_true")
    improve_rollback.set_defaults(func=cmd_improve_rollback)
    improve_status = improve_sub.add_parser("status")
    improve_status.add_argument("improvement_id")
    improve_status.set_defaults(func=cmd_improve_status)

    publish = sub.add_parser("publish", help="Prepare, scan, approve and publish a sanitized system-source snapshot to GitHub")
    publish_sub = publish.add_subparsers(dest="publish_cmd", required=True)
    publish_policy = publish_sub.add_parser("policy")
    publish_policy_sub = publish_policy.add_subparsers(dest="publish_policy_cmd", required=True)
    publish_policy_show = publish_policy_sub.add_parser("show")
    publish_policy_show.set_defaults(func=cmd_publish_policy_show)
    publish_configure = publish_sub.add_parser("configure")
    publish_configure.add_argument("--host")
    publish_configure.add_argument("--owner")
    publish_configure.add_argument("--repository")
    publish_configure.add_argument("--visibility", choices=sorted(PUBLISH_VISIBILITIES))
    publish_configure.add_argument("--description")
    publish_configure.add_argument("--license", choices=["MIT", "none"])
    publish_configure.add_argument("--copyright-holder")
    publish_configure.add_argument("--auth-method", choices=sorted(PUBLISH_AUTH_METHODS))
    publish_configure.add_argument("--token-env")
    publish_configure.add_argument("--existing-repo-mode", choices=sorted(PUBLISH_EXISTING_MODES))
    publish_configure.add_argument("--sync-mode", choices=sorted(PUBLISH_SYNC_MODES))
    publish_configure.add_argument("--after-verified", choices=sorted(PUBLISH_AFTER_VERIFIED))
    publish_configure.add_argument("--git-author-name")
    publish_configure.add_argument("--git-author-email")
    publish_configure.add_argument("--interactive", action="store_true")
    publish_configure.set_defaults(func=cmd_publish_configure)
    publish_auth = publish_sub.add_parser("auth")
    publish_auth_sub = publish_auth.add_subparsers(dest="publish_auth_cmd", required=True)
    publish_auth_status = publish_auth_sub.add_parser("status")
    publish_auth_status.set_defaults(func=cmd_publish_auth_status)
    publish_list = publish_sub.add_parser("list")
    publish_list.add_argument("--status", default="")
    publish_list.set_defaults(func=cmd_publish_list)
    publish_prepare = publish_sub.add_parser("prepare")
    publish_prepare.add_argument("--improvement-id", default="")
    publish_prepare.add_argument("--force", action="store_true")
    publish_prepare.add_argument("--scan", action=argparse.BooleanOptionalAction, default=True)
    publish_prepare.set_defaults(func=cmd_publish_prepare)
    publish_scan = publish_sub.add_parser("scan")
    publish_scan.add_argument("publication_id")
    publish_scan.set_defaults(func=cmd_publish_scan)
    publish_review = publish_sub.add_parser("review")
    publish_review.add_argument("publication_id")
    publish_review.set_defaults(func=cmd_publish_review)
    publish_approve = publish_sub.add_parser("approve")
    publish_approve.add_argument("publication_id")
    publish_approve.add_argument("--confirm", default="")
    publish_approve.add_argument("--ack-warnings", action="store_true")
    publish_approve.set_defaults(func=cmd_publish_approve)
    publish_push = publish_sub.add_parser("push")
    publish_push.add_argument("publication_id")
    publish_push.set_defaults(func=cmd_publish_push)
    publish_abort = publish_sub.add_parser("abort")
    publish_abort.add_argument("publication_id")
    publish_abort.add_argument("--reason", default="")
    publish_abort.add_argument("--delete-session", action="store_true")
    publish_abort.set_defaults(func=cmd_publish_abort)
    publish_purge = publish_sub.add_parser("purge-local")
    publish_purge.add_argument("--yes", action="store_true")
    publish_purge.set_defaults(func=cmd_publish_purge)

    command = sub.add_parser("doctor", help="Diagnose the installation and workspace")
    command.add_argument("--strict", action="store_true")
    command.set_defaults(func=cmd_doctor)

    issue = sub.add_parser("issue", help="Manage system issues")
    issue_sub = issue.add_subparsers(dest="issue_cmd", required=True)
    issue_add = issue_sub.add_parser("add")
    issue_add.add_argument("--title", required=True)
    issue_add.add_argument("--details", required=True)
    issue_add.add_argument("--severity", choices=["info", "warning", "error", "critical"], default="error")
    issue_add.add_argument("--component", default="manual")
    issue_add.add_argument("--category", default="system-function")
    issue_add.add_argument("--expected", default="")
    issue_add.add_argument("--optimization", default="")
    issue_add.add_argument("--stage", default="")
    issue_add.add_argument("--command", default="")
    issue_add.add_argument("--log", default="")
    issue_add.set_defaults(func=cmd_issue_add)
    issue_list = issue_sub.add_parser("list")
    issue_list.add_argument("--all", action="store_true")
    issue_list.set_defaults(func=cmd_issue_list)
    issue_resolve = issue_sub.add_parser("resolve")
    issue_resolve.add_argument("issue_id")
    issue_resolve.add_argument("--resolution", required=True)
    issue_resolve.set_defaults(func=cmd_issue_resolve)

    blocker = sub.add_parser("blocker", help="Manage project-specific reproduction blockers; excluded from system feedback by default")
    blocker_sub = blocker.add_subparsers(dest="blocker_cmd", required=True)
    blocker_add = blocker_sub.add_parser("add")
    blocker_add.add_argument("--title", required=True)
    blocker_add.add_argument("--details", required=True)
    blocker_add.add_argument("--severity", choices=["info", "warning", "error", "critical"], default="error")
    blocker_add.add_argument("--component", default="project")
    blocker_add.add_argument("--stage", default="")
    blocker_add.add_argument("--command", default="")
    blocker_add.add_argument("--log", default="")
    blocker_add.set_defaults(func=cmd_blocker_add)
    blocker_list = blocker_sub.add_parser("list")
    blocker_list.add_argument("--all", action="store_true")
    blocker_list.set_defaults(func=cmd_blocker_list)
    blocker_resolve = blocker_sub.add_parser("resolve")
    blocker_resolve.add_argument("blocker_id")
    blocker_resolve.add_argument("--resolution", required=True)
    blocker_resolve.set_defaults(func=cmd_blocker_resolve)

    runs = sub.add_parser("runs", help="List or select runs")
    runs_sub = runs.add_subparsers(dest="runs_cmd", required=True)
    runs_list = runs_sub.add_parser("list")
    runs_list.set_defaults(func=cmd_runs_list)
    runs_use = runs_sub.add_parser("use")
    runs_use.add_argument("run_id")
    runs_use.set_defaults(func=cmd_runs_use)

    command = sub.add_parser("paths", help="Show resolved paths")
    command.set_defaults(func=cmd_paths)

    command = sub.add_parser("feedback", help="Create a sanitized feedback bundle")
    command.add_argument("--output")
    command.add_argument("--include-logs", action="store_true")
    command.add_argument("--include-workspace-metadata", action="store_true")
    command.add_argument("--include-run-metadata", action="store_true")
    command.add_argument("--max-logs", type=int, default=5)
    command.add_argument("--max-log-kb", type=int, default=256)
    command.set_defaults(func=cmd_feedback)

    command = sub.add_parser("disable", help="Disable reproduction safety hooks for this workspace")
    command.set_defaults(func=cmd_disable)

    command = sub.add_parser("migrate-legacy", help="Migrate legacy .repro/runs state")
    command.set_defaults(func=cmd_migrate_legacy)
    return parser


def normalize_global_argv(argv: list[str]) -> list[str]:
    """Allow global path options before or after subcommands."""
    front: list[str] = []
    rest: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in {"--workspace", "--state-root"}:
            if index + 1 >= len(argv):
                rest.append(token)
                index += 1
                continue
            front.extend([token, argv[index + 1]])
            index += 2
        elif token == "--latest":
            front.append(token)
            index += 1
        else:
            rest.append(token)
            index += 1
    return front + rest


def main() -> int:
    args: argparse.Namespace | None = None
    try:
        apply_persistent_secrets()
        args = build_parser().parse_args(normalize_global_argv(sys.argv[1:]))
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except DecisionPendingError as exc:
        print(f"WAITING_FOR_DECISION: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        workspace_paths = None
        run = None
        try:
            if args is not None:
                workspace_paths = discover_workspace(getattr(args, "workspace", None), getattr(args, "state_root", None), getattr(args, "latest", False))
                run = current_run(workspace_paths)
        except Exception:
            pass
        try:
            record_issue(
                workspace_paths,
                run,
                title=f"{getattr(args, 'cmd', 'command')} 执行异常" if args else "CLI 启动异常",
                details=str(exc),
                severity="error",
                component="self-improvement" if args and getattr(args, "cmd", "") == "improve" else "reproctl",
                category="self-improvement" if args and getattr(args, "cmd", "") == "improve" else "system-function",
                stage=getattr(args, "stage", "") if args else "",
                command=" ".join(shlex.quote(value) for value in sys.argv),
            )
        except Exception:
            pass
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
