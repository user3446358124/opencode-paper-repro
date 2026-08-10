#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import runtime_engine as rte  # noqa: E402
import reproctl  # noqa: E402
import security as sec  # noqa: E402


def assert_mode(path: Path, mode: int) -> None:
    actual = path.stat().st_mode & 0o777
    assert actual == mode, (path, oct(actual), oct(mode))


def main() -> None:
    # Shared redaction engine covers headers, CLI flags, common token formats and literal secret values.
    secret = "ghp_" + "a" * 36
    sample = f"Authorization: Bearer {secret} --token {secret} api_key={secret}"
    red = sec.redact_text(sample, [secret])
    assert secret not in red and red.count("<REDACTED>") >= 2

    env = {
        "PATH": os.environ.get("PATH", ""),
        "GITHUB_PUBLISH_TOKEN": "top-secret",
        "HF_TOKEN": "hf_secret_value",
        "TOKENIZERS_PARALLELISM": "false",
        "PAPER_REPRO_CONFIG_FILE": "/secret/config.json",
        "SAFE_VALUE": "yes",
    }
    scrubbed = sec.scrub_environment(env)
    assert "GITHUB_PUBLISH_TOKEN" not in scrubbed and "HF_TOKEN" not in scrubbed
    assert "PAPER_REPRO_CONFIG_FILE" not in scrubbed
    assert scrubbed["TOKENIZERS_PARALLELISM"] == "false" and scrubbed["SAFE_VALUE"] == "yes"
    allowed = sec.scrub_environment(env, allow_names=["HF_TOKEN"])
    assert allowed["HF_TOKEN"] == "hf_secret_value" and "GITHUB_PUBLISH_TOKEN" not in allowed

    with tempfile.TemporaryDirectory(prefix="paper-repro-security-") as td:
        root = Path(td)
        run = root / "workspace" / ".paper-repro" / "runs" / "run-sec"
        workspace = root / "workspace"
        (run / "meta").mkdir(parents=True)
        (run / "execution" / "logs").mkdir(parents=True)
        (run / "meta" / "state.json").write_text(json.dumps({"status":"running","stage":"execution","pipeline":{"steps":[]}}))
        paths = rte.RuntimePaths(run)
        paths.ensure()

        # Project task gets no control-plane secrets by default, even when the scheduler process has them.
        os.environ["GITHUB_PUBLISH_TOKEN"] = "audit-super-secret"
        out = workspace / "secret-visible.txt"
        task = rte.add_task(
            paths, display_name="scrub", stage="execution",
            command=f"printf '%s' \"${{GITHUB_PUBLISH_TOKEN:-MISSING}}\" > {out}",
            workspace=str(workspace), execution_env={}, gpu_count=0, task_id="SEC-SCRUB",
            sandbox_policy={"mode":"trusted-off","backend":"auto","network":"off"},
        )
        rte.update_task(paths, task["task_id"], state="running", gpu_ids=[])
        rc = rte.task_worker(paths, task["task_id"])
        assert rc == 0 and out.read_text() == "MISSING"

        # Explicit workspace/task-scoped authorization is the only supported secret injection path.
        out2 = workspace / "secret-allowed.txt"
        task2 = rte.add_task(
            paths, display_name="allow", stage="execution",
            command=f"printf '%s' \"${{GITHUB_PUBLISH_TOKEN:-MISSING}}\" > {out2}",
            workspace=str(workspace), execution_env={}, gpu_count=0, task_id="SEC-ALLOW",
            sandbox_policy={"mode":"trusted-off","backend":"auto","network":"off"},
            secret_env=["GITHUB_PUBLISH_TOKEN"],
        )
        rte.update_task(paths, task2["task_id"], state="running", gpu_ids=[])
        rc = rte.task_worker(paths, task2["task_id"])
        assert rc == 0 and out2.read_text() == "audit-super-secret"
        del os.environ["GITHUB_PUBLISH_TOKEN"]

        # Fail closed when sandboxing is requested but bwrap is unavailable.
        original_which = rte.shutil_which
        rte.shutil_which = lambda name: None if name == "bwrap" else original_which(name)
        try:
            try:
                rte.build_sandbox_argv(paths, {"workspace":str(workspace),"sandbox":{"mode":"auto"}}, ["true"], {}, [])
                raise AssertionError("sandbox auto accepted missing bwrap")
            except rte.RuntimeErrorEx as exc:
                assert "sandbox" in str(exc).lower() and "bwrap" in str(exc).lower()
        finally:
            rte.shutil_which = original_which

        # The generated bubblewrap command hides the real home and binds only the workspace writable.
        rte.shutil_which = lambda name: "/usr/bin/bwrap" if name == "bwrap" else original_which(name)
        external_root = root / "external-data"
        external_root.mkdir()
        try:
            sandbox_argv, sandbox_state = rte.build_sandbox_argv(
                paths,
                {"workspace": str(workspace), "execution_env": {}, "sandbox": {"mode":"auto","network":"off", "allowed_roots":[str(external_root)]}},
                ["bash", "-lc", "true"], {}, [],
            )
            joined = " ".join(sandbox_argv)
            assert sandbox_state["enabled"] is True and sandbox_state["backend"] == "bubblewrap"
            assert "--bind" in sandbox_argv and str(workspace.resolve()) in sandbox_argv
            assert str(external_root.resolve()) in sandbox_argv
            assert "--unshare-net" in sandbox_argv
            assert not ("--ro-bind / /" in joined), joined
            assert "/usr" in sandbox_argv and "/etc/shadow" not in sandbox_argv
            # Real paper-repro control state is hidden; only cache + task exchange are re-exposed.
            state_home = workspace / ".paper-repro"
            assert f"--tmpfs {state_home}" in joined
            assert f"--bind {state_home / 'cache'} {state_home / 'cache'}" in joined
            assert f"--bind {run / 'execution' / 'sandbox' / 'task'} {run}" in joined
            # The sandbox receives a synthetic HOME rather than the real home tree.
            assert "/tmp/paper-repro-home" in sandbox_argv
        finally:
            rte.shutil_which = original_which

        # Conda exposure is least-privilege: base/control are read-only, sibling envs
        # are hidden, and only the current project env is writable.
        fake_base = root / "miniconda"
        fake_control = fake_base / "envs" / "control"
        fake_project = fake_base / "envs" / "project"
        (fake_base / "bin").mkdir(parents=True)
        fake_control.mkdir(parents=True)
        fake_project.mkdir(parents=True)
        fake_conda = fake_base / "bin" / "conda"
        fake_conda.write_text("#!/bin/sh\nexit 0\n")
        fake_conda.chmod(0o755)
        old_cp = os.environ.get("CONDA_PREFIX")
        old_ce = os.environ.get("PAPER_REPRO_CONDA_EXE")
        os.environ["CONDA_PREFIX"] = str(fake_control)
        os.environ["PAPER_REPRO_CONDA_EXE"] = str(fake_conda)
        rte.shutil_which = lambda name: "/usr/bin/bwrap" if name == "bwrap" else original_which(name)
        try:
            conda_argv, _ = rte.build_sandbox_argv(
                paths,
                {"workspace": str(workspace), "execution_env": {"prefix":str(fake_project)}, "sandbox":{"mode":"auto","network":"off"}},
                ["true"], {}, [],
            )
            cj = " ".join(conda_argv)
            assert f"--ro-bind {fake_base} {fake_base}" in cj
            assert f"--tmpfs {fake_base / 'envs'}" in cj
            assert f"--ro-bind {fake_control} {fake_control}" in cj
            assert f"--bind {fake_project} {fake_project}" in cj
            try:
                rte.build_sandbox_argv(
                    paths,
                    {"workspace":str(workspace), "execution_env":{"prefix":str(fake_control)}, "sandbox":{"mode":"auto"}},
                    ["true"], {}, [],
                )
                raise AssertionError("sandbox accepted project env == control env")
            except rte.RuntimeErrorEx as exc:
                assert "project Conda equals" in str(exc)
        finally:
            if old_cp is None: os.environ.pop("CONDA_PREFIX", None)
            else: os.environ["CONDA_PREFIX"] = old_cp
            if old_ce is None: os.environ.pop("PAPER_REPRO_CONDA_EXE", None)
            else: os.environ["PAPER_REPRO_CONDA_EXE"] = old_ce
            rte.shutil_which = original_which

        # Unified config/secrets must not be placed inside the writable project/run tree.
        rte.shutil_which = lambda name: "/usr/bin/bwrap" if name == "bwrap" else original_which(name)
        old_cfg = os.environ.get("PAPER_REPRO_CONFIG_FILE")
        os.environ["PAPER_REPRO_CONFIG_FILE"] = str(workspace / ".paper-repro" / "unsafe-config.json")
        try:
            try:
                rte.build_sandbox_argv(
                    paths,
                    {"workspace": str(workspace), "execution_env": {}, "sandbox": {"mode":"auto","network":"off"}},
                    ["true"], {}, [],
                )
                raise AssertionError("sandbox accepted global config inside writable workspace")
            except rte.RuntimeErrorEx as exc:
                assert "Security boundary violation" in str(exc)
        finally:
            if old_cfg is None:
                os.environ.pop("PAPER_REPRO_CONFIG_FILE", None)
            else:
                os.environ["PAPER_REPRO_CONFIG_FILE"] = old_cfg
            rte.shutil_which = original_which

        # Public snapshots reject nested symlinks instead of following them.
        source = root / "source"
        (source / "docs").mkdir(parents=True)
        private = root / "private.txt"
        private.write_text("PRIVATE-RESEARCH")
        (source / "docs" / "linked.txt").symlink_to(private)
        try:
            reproctl._copy_public_source(source, root / "public")
            raise AssertionError("nested publication symlink was accepted")
        except reproctl.ReproError as exc:
            assert "符号链接" in str(exc)

        # Private state writes use user-only permissions.
        private_json = root / "private-state.json"
        reproctl.atomic_json(private_json, {"ok": True})
        assert_mode(private_json, 0o600)

        # Existing v2.2-era workspace state can be repaired to private 700/600 modes.
        legacy = workspace / ".paper-repro" / "legacy-visible.txt"
        legacy.write_text("legacy")
        legacy.chmod(0o644)
        (workspace / ".paper-repro").chmod(0o755)
        repaired = reproctl._repair_private_tree(workspace / ".paper-repro")
        assert repaired["files"] >= 1
        assert_mode(workspace / ".paper-repro", 0o700)
        assert_mode(legacy, 0o600)

        # Download roots are bounded to workspace/cache unless user explicitly expands them.
        wp = reproctl.WorkspacePaths(workspace=workspace, state_home=workspace / ".paper-repro")
        roots = reproctl.allowed_download_roots(wp)
        assert any(reproctl._path_within(workspace / "data.bin", r) for r in roots)
        assert not any(reproctl._path_within(root / "outside.bin", r) for r in roots)

        # Installer rejects catastrophic install paths before any delete/copy operation.
        fake_conda = root / "control"
        (fake_conda / "bin").mkdir(parents=True)
        env2 = os.environ.copy()
        env2.update({
            "CONDA_PREFIX": str(fake_conda), "CONDA_DEFAULT_ENV": "paper-repro-control-test",
            "PAPER_REPRO_INSTALL_HOME": "/", "PAPER_REPRO_SKIP_DEPENDENCIES": "1",
            "PAPER_REPRO_GLOBAL_INSTALL": "0", "PYTHON": sys.executable,
        })
        proc = subprocess.run(["bash", str(ROOT / "bootstrap.sh")], env=env2, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert proc.returncode != 0 and "危险" in (proc.stdout + proc.stderr)

        # Uninstaller requires a valid install marker before rm -rf.
        fake_install = root / "not-an-install"
        fake_install.mkdir()
        env3 = os.environ.copy()
        env3.update({"CONDA_PREFIX": str(fake_conda), "PAPER_REPRO_INSTALL_HOME": str(fake_install)})
        proc = subprocess.run(["bash", str(ROOT / "scripts" / "uninstall.sh")], env=env3, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert proc.returncode != 0 and "install.json" in (proc.stdout + proc.stderr)

    plugin = (ROOT / ".opencode" / "plugins" / "repro-audit.ts").read_text(encoding="utf-8")
    assert "paper-repro" in plugin and "sensitiveShellPath" in plugin and "secretEnvKey" in plugin
    assert "sensitiveControlCommand" in plugin and r"\/proc\/" in plugin and r"secrets\s+(?:exec|edit)" in plugin
    assert "paperReproControlMode" in plugin and "customSensitiveRoots" in plugin and "liveSecretValues" in plugin
    controller = (ROOT / "scripts" / "reproctl.py").read_text(encoding="utf-8")
    assert 'tests/security_hardening_test.py' in controller and 'scripts/security.py' in controller and 'scripts/runtime_engine.py' in controller
    assert '@brave/brave-search-mcp-server@2.1.0' in controller
    pins = json.loads((ROOT / "configs" / "dependency-pins.json").read_text(encoding="utf-8"))
    assert pins["pin_level"] == "direct-version-pinned" and pins["artifact_hash_lock"] is False
    assert pins["bubblewrap_conda"] == "0.11.2"
    bootstrap = (ROOT / "bootstrap.sh").read_text(encoding="utf-8")
    assert 'BWRAP_SPEC="${PAPER_REPRO_BWRAP_SPEC:-bubblewrap=0.11.2}"' in bootstrap
    assert 'conda install -y -c conda-forge "$BWRAP_SPEC"' in bootstrap
    cfg = (ROOT / "opencode.jsonc").read_text(encoding="utf-8")
    assert '"~/.config/paper-repro/**": "deny"' in cfg and '"~/.ssh/**": "deny"' in cfg

    print("SECURITY_HARDENING_TEST_OK")


if __name__ == "__main__":
    main()
