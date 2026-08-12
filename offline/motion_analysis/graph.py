"""SkeletonGraph — per-frame 3D graph + sequence + intra extraction (Phase 3).

Paper G_t=(V_t,E_t) with joint name/index/x/y/z and edge source/target/vector/length.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any
import numpy as np

from .topology import SMPLX_NAMES, build_edges
from .features import vertex_motion, edge_motion, pelvis_centered, scale_normalized


@dataclass(frozen=True)
class SkeletonGraph:
    """One frame's graph. Positions are (J,3) in the sequence's coordinate space."""

    frame_index: int
    joint_names: tuple[str, ...]
    positions: np.ndarray  # (J,3) float32
    edges: tuple[tuple[int, int], ...]

    @property
    def joints(self) -> list[dict[str, Any]]:
        return [
            {"name": self.joint_names[i], "index": i, "x": float(self.positions[i, 0]), "y": float(self.positions[i, 1]), "z": float(self.positions[i, 2])}
            for i in range(len(self.joint_names))
        ]

    @property
    def edge_vectors(self) -> list[dict[str, Any]]:
        out = []
        for s, d in self.edges:
            v = self.positions[s] - self.positions[d]
            out.append({"source": s, "target": d, "source_name": self.joint_names[s], "target_name": self.joint_names[d], "vector": v.tolist(), "length": float(np.linalg.norm(v))})
        return out


@dataclass
class SkeletonGraphSequence:
    """Ordered sequence of SkeletonGraphs — the whole clip."""

    joint_names: list[str]
    positions: np.ndarray  # (N,J,3) float32
    edges: list[tuple[int, int]]
    fps: float = 25.0
    coordinate_space: str = "camera"  # raw SMPL-X cam_trans frame
    normalization: str = "raw"  # raw | pelvis_centered | scale_normalized

    def __post_init__(self) -> None:
        n, j, c = self.positions.shape
        assert c == 3
        assert j == len(self.joint_names)
        assert all(0 <= s < j and 0 <= d < j for s, d in self.edges)

    @property
    def frame_count(self) -> int:
        return int(self.positions.shape[0])

    def graph_at(self, t: int) -> SkeletonGraph:
        return SkeletonGraph(frame_index=t, joint_names=tuple(self.joint_names), positions=self.positions[t].astype(np.float32), edges=tuple(self.edges))

    def normalized(self, mode: str = "pelvis_centered") -> "SkeletonGraphSequence":
        if mode == "raw":
            return self
        pos = self.positions.astype(np.float32)
        if mode == "pelvis_centered":
            pos = pelvis_centered(pos)
            norm = "pelvis_centered"
        elif mode == "scale_normalized":
            pos, _ = scale_normalized(pelvis_centered(pos))
            norm = "scale_normalized"
        elif mode == "shoulder_width":
            from .features import shoulder_width_normalized

            pos, _ = shoulder_width_normalized(pelvis_centered(pos))
            norm = "shoulder_width"
        else:
            raise ValueError(f"unknown normalization {mode}")
        return SkeletonGraphSequence(joint_names=self.joint_names, positions=pos, edges=self.edges, fps=self.fps, coordinate_space=self.coordinate_space, normalization=norm)

    # Serialization (round-trip)
    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(p, joint_names=np.array(self.joint_names), positions=self.positions.astype(np.float32), edges=np.array(self.edges, dtype=np.int32), fps=np.float32(self.fps), coordinate_space=self.coordinate_space, normalization=self.normalization)

    @classmethod
    def load(cls, path: str | Path) -> "SkeletonGraphSequence":
        d = np.load(path, allow_pickle=False)
        names = [str(x) for x in d["joint_names"]]
        return cls(joint_names=names, positions=d["positions"], edges=[tuple(x) for x in d["edges"].tolist()], fps=float(d["fps"]), coordinate_space=str(d["coordinate_space"]), normalization=str(d["normalization"]))


@dataclass(frozen=True)
class MotionFrameResult:
    """Result of intra motion extraction (paper Eqs 4-8). Temporal order preserved."""

    original_indices: np.ndarray  # (N_retained,) int
    retention_mask: np.ndarray  # (N,) bool
    vertex_motion: np.ndarray  # (N-1,J)
    edge_motion: np.ndarray  # (N-1,E)
    threshold_vertex: float
    threshold_edge: float
    mode: str  # paper_mode | percentile_mode | absolute_mode


def extract_motion_frames(
    seq: SkeletonGraphSequence,
    mode: str = "paper_mode",
    threshold: float | None = None,
    percentile: float = 75.0,
) -> MotionFrameResult:
    """Paper-derived intra extraction.

    Paper thresholds are max-based (Eqs 4-7, notation partially corrupted in supplied text).
    We expose the threshold as config and document interpretation; don't invent math.

    - paper_mode: threshold = max_motion * 0.2 (paper reports 0.2 as tested value, not universal). Requires verification against PDF.
    - percentile_mode: threshold = percentile of motion magnitudes (engineering extension).
    - absolute_mode: threshold = explicit float (engineering extension).
    Combination: intersection of vertex and edge selections as per paper (document Eq 8 inconsistency).
    """
    vm = vertex_motion(seq.positions)  # (N-1,J)
    em = edge_motion(seq.positions, seq.edges)  # (N-1,E)

    # Frame-level max motion (max over joints/edges)
    vm_max = vm.max(axis=1) if vm.size else np.zeros(0)  # (N-1,)
    em_max = em.max(axis=1) if em.size else np.zeros(0)

    n = seq.frame_count
    if n <= 1:
        mask = np.ones(n, dtype=bool)
        return MotionFrameResult(original_indices=np.arange(n), retention_mask=mask, vertex_motion=vm, edge_motion=em, threshold_vertex=0.0, threshold_edge=0.0, mode=mode)

    if mode == "paper_mode":
        # Paper: threshold from max motion values; 0.2 is reported tested value.
        th_v = float(vm_max.max() * 0.2) if vm_max.size else 0.0
        th_e = float(em_max.max() * 0.2) if em_max.size else 0.0
        if threshold is not None:
            th_v = th_e = float(threshold)
    elif mode == "percentile_mode":
        th_v = float(np.percentile(vm_max, percentile)) if vm_max.size else 0.0
        th_e = float(np.percentile(em_max, percentile)) if em_max.size else 0.0
    elif mode == "absolute_mode":
        if threshold is None:
            raise ValueError("absolute_mode requires threshold")
        th_v = th_e = float(threshold)
    else:
        raise ValueError(f"unknown mode {mode}")

    # Mark frame t as motion if either vertex or edge max exceeds threshold (intersection would be
    # stricter; paper's Eq 8 is ambiguous — we document as union and note alternative).
    # We use union to not drop too aggressively; caller can switch to intersection if paper clarifies.
    motion = (vm_max > th_v) | (em_max > th_e)  # (N-1,)
    # retention mask for N frames: keep first frame always, then keep t+1 if motion[t] true
    mask = np.zeros(n, dtype=bool)
    mask[0] = True
    if n > 1:
        mask[1:] = motion
    # If too aggressive, ensure at least 25% retained (paper reports ~25% reduction, not claim)
    if mask.sum() < 2 and n > 2:
        # keep highest motion frames up to 25%
        k = max(2, n // 4)
        order = np.argsort(vm_max + em_max)[::-1]
        for idx in order[:k]:
            mask[idx + 1] = True

    indices = np.where(mask)[0]
    return MotionFrameResult(original_indices=indices, retention_mask=mask, vertex_motion=vm, edge_motion=em, threshold_vertex=th_v, threshold_edge=th_e, mode=mode)


def from_npz(npz_path: str | Path, fps: float = 25.0) -> SkeletonGraphSequence:
    """Build SkeletonGraphSequence from Phase 2 SMPLest-X NPZ (smplx_joint_cam)."""
    d = np.load(npz_path, allow_pickle=False)
    jc = d["smplx_joint_cam"]  # (N,J,3)
    n, j, c = jc.shape
    assert c == 3
    names = (SMPLX_NAMES[:j] if j <= len(SMPLX_NAMES) else SMPLX_NAMES + [f"ext_{i}" for i in range(len(SMPLX_NAMES), j)])
    edges = build_edges(names)
    return SkeletonGraphSequence(joint_names=names, positions=jc.astype(np.float32), edges=edges, fps=fps, coordinate_space="camera", normalization="raw")
