"""Graph matching — paper Eq 9, offline research only (Phase 4)."""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from .graph import SkeletonGraph, SkeletonGraphSequence
from .topology import SMPLX_NAMES


@dataclass(frozen=True)
class FrameMatch:
    vertex_distances: np.ndarray  # (J,)
    edge_distances: np.ndarray  # (E,)
    vertex_score: float  # mean over joints
    edge_score: float
    combined: float
    # hand-aware
    body_score: float
    left_hand_score: float
    right_hand_score: float
    finger_score: float


def _region_indices(joint_names: list[str]) -> dict[str, list[int]]:
    body, lhand, rhand, fingers = [], [], [], []
    for i, n in enumerate(joint_names):
        if n.startswith("l_") or n.startswith("r_"):
            fingers.append(i)
            if n.startswith("l_"):
                lhand.append(i)
            else:
                rhand.append(i)
        elif n in ("pelvis", "left_hip", "right_hip", "spine1", "spine2", "spine3", "neck", "head", "jaw", "left_collar", "right_collar", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_knee", "right_knee", "left_ankle", "right_ankle", "left_foot", "right_foot", "spine1", "spine2"):
            body.append(i)
        else:
            # fallback: if name contains hand, treat as fingers already
            if "shoulder" in n or "elbow" in n or "wrist" in n or "hip" in n or "knee" in n or "ankle" in n or "pelvis" in n or "spine" in n:
                body.append(i)
    # ensure body includes non-finger joints
    if not body:
        body = [i for i, n in enumerate(joint_names) if not n.startswith(("l_", "r_"))]
    return {"body": body, "left_hand": lhand, "right_hand": rhand, "fingers": fingers}


def compare_frames(q: SkeletonGraph, d: SkeletonGraph, edges: list[tuple[int, int]] | None = None) -> FrameMatch:
    """d_v(i)=||v_Q,i - v_D,i||, d_e=||e_Q - e_D||, combined = mean."""
    assert q.positions.shape == d.positions.shape
    vd = np.linalg.norm(q.positions - d.positions, axis=1)  # (J,)
    # edges
    if edges is None:
        edges = list(q.edges)
    q_e = np.stack([q.positions[s] - q.positions[t] for s, t in edges], axis=0) if edges else np.zeros((0, 3))
    d_e = np.stack([d.positions[s] - d.positions[t] for s, t in edges], axis=0) if edges else np.zeros((0, 3))
    ed = np.linalg.norm(q_e - d_e, axis=1) if edges else np.zeros(0)

    v_score = float(vd.mean()) if vd.size else 0.0
    e_score = float(ed.mean()) if ed.size else 0.0
    combined = 0.5 * v_score + 0.5 * e_score

    regions = _region_indices(list(q.joint_names))
    def mean_for(idxs: list[int]) -> float:
        return float(vd[idxs].mean()) if idxs else combined
    body = mean_for(regions["body"])
    lh = mean_for(regions["left_hand"])
    rh = mean_for(regions["right_hand"])
    fing = mean_for(regions["fingers"])

    return FrameMatch(vertex_distances=vd, edge_distances=ed, vertex_score=v_score, edge_score=e_score, combined=combined, body_score=body, left_hand_score=lh, right_hand_score=rh, finger_score=fing)


def compare_sequences(q_seq: SkeletonGraphSequence, d_seq: SkeletonGraphSequence) -> dict[str, np.ndarray]:
    """M_V (Nq x Nd) vertex similarity, M_E, combined. Rows query, cols dataset."""
    nq, nd = q_seq.frame_count, d_seq.frame_count
    Mv = np.zeros((nq, nd), dtype=np.float32)
    Me = np.zeros((nq, nd), dtype=np.float32)
    Mc = np.zeros((nq, nd), dtype=np.float32)
    for i in range(nq):
        qg = q_seq.graph_at(i)
        for j in range(nd):
            dg = d_seq.graph_at(j)
            m = compare_frames(qg, dg, q_seq.edges)
            Mv[i, j] = m.vertex_score
            Me[i, j] = m.edge_score
            Mc[i, j] = m.combined
    return {"M_V": Mv, "M_E": Me, "combined": Mc, "vertex": Mv, "edge": Me}


def normalize_modes(seq: SkeletonGraphSequence) -> dict[str, SkeletonGraphSequence]:
    """Return raw / pelvis_centered / scale_normalized variants for Phase 4 test 2."""
    return {
        "raw": seq,
        "pelvis_centered": seq.normalized("pelvis_centered"),
        "scale_normalized": seq.normalized("scale_normalized"),
    }
