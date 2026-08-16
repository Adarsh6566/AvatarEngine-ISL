"""
_smplx_common — helpers for SMPL-X modes. No auto-download per user request.

If local SMPLX assets not present, callers should raise 501, not fallback to dummy.
All paths stay inside pipeline/.models/smplx and pipeline/.cache.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from .schemas import CANONICAL_JOINTS

PIPELINE_DIR = Path(__file__).parent.parent
MODELS_DIR = PIPELINE_DIR / ".models" / "smplx"
CACHE_DIR = PIPELINE_DIR / ".cache"

# Expected local files (user places these; no download)
EXPECTED_FILES = [
    MODELS_DIR / "SMPLX_NEUTRAL.npz",  # or .pkl
    MODELS_DIR / "SMPLX_NEUTRAL.pkl",
    MODELS_DIR / "SMPLX_MALE.pkl",
    MODELS_DIR / "SMPLX_FEMALE.pkl",
]


def check_smplx_available() -> tuple[bool, str]:
    """Return (available, detail). Available if at least one SMPLX model exists locally."""
    for p in EXPECTED_FILES:
        if p.exists() and p.stat().st_size > 1_000_000:
            return True, str(p)
    # also accept any .npz/.pkl in smplx dir
    if MODELS_DIR.exists():
        for f in MODELS_DIR.glob("*"):
            if f.suffix in (".npz", ".pkl") and f.stat().st_size > 1_000_000:
                return True, str(f)
    return False, (
        f"SMPL-X model not found in {MODELS_DIR}. "
        "Place SMPLX_NEUTRAL.npz/.pkl there (from smplx.is.tue.mpg.de). "
        "No auto-download per config; all artifacts must stay in pipeline/."
    )


def check_torch_available() -> tuple[bool, str]:
    try:
        import torch  # type: ignore

        cuda = bool(getattr(torch, "cuda", None) and torch.cuda.is_available())
        return True, f"torch {torch.__version__} cuda={cuda}"
    except Exception as e:
        return False, f"torch not installed: {e}"


def smplx_to_canonical_map(smplx_joints, confs=None):
    """
    Map SMPL-X 55 joints to CANONICAL_JOINTS. Override in full impl.
    Stub returns None for now — real mapping needs smplx forward.
    """
    # placeholder: caller should implement actual mapping
    return {}
