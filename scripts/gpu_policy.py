"""GPU device selection policy for paper-repro exec.

Standalone module so it can be reasoned about and tested without importing the
full CLI. reproctl.py injects its gpu_rows() callable for testability.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable

GPU_EXPLICIT = re.compile(r"(^|[\s;&|(])(export\s+)?CUDA_VISIBLE_DEVICES\s*=")


def _card_sort_key(row: dict[str, Any]) -> tuple[int, int]:
    """Primary key: used memory (MiB); secondary key: GPU utilization (%)."""
    try:
        memory = int(row.get("memory_used_mb") or 0)
    except (TypeError, ValueError):
        memory = 0
    try:
        util = int(row.get("util_gpu_pct") or 0)
    except (TypeError, ValueError):
        util = 0
    return memory, util


def resolve_gpus(
    gpus: str,
    command: str,
    gpu_rows: Callable[[], list[dict[str, Any]]],
    exclude: Iterable[str] = (),
) -> tuple[str | None, str]:
    """Decide CUDA_VISIBLE_DEVICES for a project command.

    gpus: policy string: auto / all / none / explicit list such as "0,1".
    command: the project command text (to honor explicit CUDA_VISIBLE_DEVICES=).
    gpu_rows: callable returning GPU snapshots (index, memory_used_mb, ...).
    exclude: GPU indexes already allocated by commands of the current run;
             auto selection avoids them and falls back to all cards when every
             card is excluded (no deadlock).

    Returns (value_or_None, human_readable_note). Never overrides an explicit
    CUDA_VISIBLE_DEVICES=... written inside the command itself.
    """
    excluded = {str(item) for item in exclude if str(item) != ""}
    if GPU_EXPLICIT.search(command):
        return None, "命令内已显式设置 CUDA_VISIBLE_DEVICES，未覆盖"
    if gpus == "none":
        return None, "CUDA_VISIBLE_DEVICES 未设置（--gpus none）"
    if gpus == "all":
        return None, "全部 GPU 可见（--gpus all）"
    rows = gpu_rows() or []
    if gpus == "auto":
        if not rows:
            return None, "nvidia-smi 不可用或无 GPU，未设置 CUDA_VISIBLE_DEVICES"
        candidates = [row for row in rows if str(row.get("index")) not in excluded]
        if not candidates:
            candidates = rows  # every card is already allocated: fall back
        chosen = min(candidates, key=_card_sort_key)
        index = str(chosen.get("index", "0"))
        note = f"自动选择最空闲 GPU {index}（已用显存 {chosen.get('memory_used_mb')} MiB）"
        if excluded and str(index) not in excluded:
            note += "；已避开本 run 先前分配的 GPU"
        return index, note
    requested = [part.strip() for part in gpus.split(",") if part.strip()]
    available = {str(row.get("index")) for row in rows} if rows else set()
    if available:
        missing = [index for index in requested if index not in available]
        if missing:
            raise ValueError(
                f"GPU 索引不存在：{', '.join(missing)}"
                f"（可用：{', '.join(sorted(available)) or '无'}）"
            )
    return ",".join(requested), f"指定 GPU：{gpus}"
