"""Device selection — run inference on CUDA when torch has it, else CPU.

Both YOLO extractors go through Ultralytics, whose predict call defaults to a
device string that resolves to CPU unless it is told otherwise. Resolving the
choice here keeps it in one place and lets an operator pin a device through
PIPELINE_DEVICE (e.g. "cpu", "cuda:0") when auto-detection picks wrong.

MediaPipe is deliberately not covered: its Python wheels expose only the CPU
delegate on Windows, so pose/hand landmarking stays on CPU regardless.
"""

from __future__ import annotations

import os
from functools import lru_cache


@lru_cache(maxsize=1)
def select_device() -> str:
    """Torch device string for inference — "cuda:N" or "cpu"."""
    override = os.environ.get("PIPELINE_DEVICE", "").strip()
    if override:
        return override
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            return "cuda:0"
    except Exception:
        pass
    return "cpu"


@lru_cache(maxsize=1)
def device_label() -> str:
    """Human-readable device, for /api/health and meta.estimator."""
    dev = select_device()
    if not dev.startswith("cuda"):
        return dev
    try:
        import torch  # type: ignore

        index = int(dev.split(":", 1)[1]) if ":" in dev else 0
        return f"{dev} ({torch.cuda.get_device_name(index)})"
    except Exception:
        return dev
