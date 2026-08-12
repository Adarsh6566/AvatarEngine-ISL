"""Phase 3-4 — 3D graph + matching + EEMGM (offline research, no runtime dependency)."""
from .graph import SkeletonGraph, SkeletonGraphSequence, MotionFrameResult
from .topology import SMPLX_NAMES, build_edges, topology_table

try:
    from .graph_matching import compare_frames, compare_sequences
    from .eemgm import SignDatabase, SignEntry, eemgm
except Exception:  # optional during install without numpy
    compare_frames = compare_sequences = None  # type: ignore
    SignDatabase = SignEntry = eemgm = None  # type: ignore

__all__ = ["SkeletonGraph", "SkeletonGraphSequence", "MotionFrameResult", "SMPLX_NAMES", "build_edges", "topology_table", "compare_frames", "compare_sequences", "SignDatabase", "SignEntry", "eemgm"]
