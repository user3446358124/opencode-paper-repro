#!/usr/bin/env python3
from __future__ import annotations

import base64
import os
import re
import urllib.parse
from pathlib import Path
from typing import Iterable, Mapping

# Security helpers shared by reproctl and the persistent runtime.
SECRET_NAME_RE = re.compile(
    r"(?i)(?:^|_)(?:api_?key|access_?key|secret(?:_?key)?|token|password|passwd|authorization|auth_?token|credential|private_?key)(?:$|_)"
)
CONTROL_PRIVATE_ENV = {
    "PAPER_REPRO_CONFIG_HOME",
    "PAPER_REPRO_CONFIG_FILE",
    "PAPER_REPRO_SECRETS_FILE",
    "PAPER_REPRO_MCP_CONFIG",
    "OPENCODE_CONFIG",
    "SSH_AUTH_SOCK",
    "GIT_ASKPASS",
    "GITHUB_PUBLISH_TOKEN",
}

_PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([^\s,;]+)"),
    re.compile(r"(?i)((?:api[_-]?key|access[_-]?key|token|password|passwd|secret|authorization)\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"(?i)((?:--api-key|--token|--password|--secret|--access-token)\s+)([^\s]+)"),
    re.compile(r"(?i)(https?://)([^/@\s:]+):([^/@\s]+)@"),
    re.compile(r"(?i)([?&](?:access_token|auth|api_key|key|password|signature|sig|token|x-amz-signature)=)([^&\s]+)"),
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|hf_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})\b"),
]


def is_secret_env_name(name: str) -> bool:
    upper = str(name).upper()
    return upper in CONTROL_PRIVATE_ENV or bool(SECRET_NAME_RE.search(upper))


def scrub_environment(
    env: Mapping[str, str],
    *,
    allow_names: Iterable[str] = (),
    extra_secret_names: Iterable[str] = (),
) -> dict[str, str]:
    allow = {str(x) for x in allow_names}
    exact = {str(x) for x in extra_secret_names}
    result: dict[str, str] = {}
    for name, value in env.items():
        if name in allow:
            result[name] = value
            continue
        if name in exact or is_secret_env_name(name):
            continue
        result[name] = value
    # Never let a project process discover the persistent configuration location.
    for name in CONTROL_PRIVATE_ENV:
        if name not in allow:
            result.pop(name, None)
    return result


def redact_text(text: object, secret_values: Iterable[str] = ()) -> str:
    out = str(text)
    literals = [str(v) for v in secret_values if isinstance(v, str) and len(v) >= 6]
    for value in sorted(set(literals), key=len, reverse=True):
        variants = {value, urllib.parse.quote(value, safe="")}
        try:
            variants.add(base64.b64encode(value.encode()).decode())
        except Exception:
            pass
        for variant in variants:
            if variant:
                out = out.replace(variant, "<REDACTED>")
    # Structured patterns.
    out = _PATTERNS[0].sub(lambda m: m.group(1) + "<REDACTED>", out)
    out = _PATTERNS[1].sub(lambda m: m.group(1) + "<REDACTED>", out)
    out = _PATTERNS[2].sub(lambda m: m.group(1) + "<REDACTED>", out)
    out = _PATTERNS[3].sub(lambda m: m.group(1) + "<REDACTED>@", out)
    out = _PATTERNS[4].sub(lambda m: m.group(1) + "<REDACTED>", out)
    out = _PATTERNS[5].sub("<REDACTED>", out)
    return out


def find_symlinks(root: str | Path) -> list[Path]:
    base = Path(root)
    found: list[Path] = []
    if base.is_symlink():
        return [base]
    for current, dirs, files in os.walk(base, followlinks=False):
        cur = Path(current)
        for name in list(dirs) + list(files):
            candidate = cur / name
            if candidate.is_symlink():
                found.append(candidate)
    return found


def secure_umask() -> None:
    os.umask(0o077)
