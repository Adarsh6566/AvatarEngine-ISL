"""Normalization + intra motion features (Phase 3, paper Eqs 4-7).

All functions operate on SkeletonGraphSequence; raw NPZ is never mutated.
"""
from __future__ import annotations

import numpy as np

from .topology import SMPLX_NAMES


def pelvis_centered(positions: np.ndarray, pelvis_idx: int = 0) -> np.ndarray:
    """Subtract pelvis (idx 0) per frame. positions: (N,J,3) -> (N,J,3)."""
    return positions - positions[:, pelvis_idx : pelvis_idx + 1, :]


def scale_normalized(positions: np.ndarray, ref: float | None = None) -> tuple[np.ndarray, float]:
    """Unit-torso scale: mean hip→head distance =1. Returns (scaled, scale)."""
    # pelvis 0, head 15
    torso = np.linalg.norm(positions[:, 15, :] - positions[:, 0, :], axis=1)
    scale = float(np.mean(torso)) if ref is None else float(ref)
    if scale < 1e-6:
        scale = 1.0
    return positions / scale, scale


def shoulder_width_normalized(positions: np.ndarray) -> tuple[np.ndarray, float]:
    """Scale by mean shoulder width (left_shoulder 16 → right_shoulder 17)."""
    w = np.linalg.norm(positions[:, 16, :] - positions[:, 17, :], axis=1)
    scale = float(np.mean(w))
    if scale < 1e-6:
        scale = 1.0
    return positions / scale, scale


def vertex_motion(positions: np.ndarray) -> np.ndarray:
    """m_v(i,t)=||v_i(t+1)-v_i(t)||_2 → (N-1, J)."""
    diff = positions[1:] - positions[:-1]  # (N-1,J,3)
    return np.linalg.norm(diff, axis=2)  # (N-1,J)


def edge_vectors(positions: np.ndarray, edges: list[tuple[int, int]]) -> np.ndarray:
    """e_ij(t)=v_i(t)-v_j(t) → (N, E, 3)."""
    if not edges:
        return np.zeros((positions.shape[0], 0, 3), dtype=np.float32)
    ev = np.stack([positions[:, s, :] - positions[:, d, :] for s, d in edges], axis=1)
    return ev.astype(np.float32)


def edge_motion(positions: np.ndarray, edges: list[tuple[int, int]]) -> np.ndarray:
    """m_e(ij,t)=||e_ij(t+1)-e_ij(t)||_2 → (N-1, E)."""
    ev = edge_vectors(positions, edges)  # (N,E,3)
    diff = ev[1:] - ev[:-1]  # (N-1,E,3)
    return np.linalg.norm(diff, axis=2)
