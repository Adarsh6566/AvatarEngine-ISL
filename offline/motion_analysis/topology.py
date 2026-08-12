"""SMPL-X topology — edges from joint names (Phase 3).

Uses the actual SMPL-X joint count (55 core) from export_smplestx_npz.py,
not the paper's 57-marker Vicon. Extra joints (J>55) are labelled extended.
"""
from __future__ import annotations

# Authoritative SMPL-X 0..54 names (matches offline/colab/export_smplestx_npz.py _SMPLX_NAMES)
SMPLX_NAMES: list[str] = [
    "pelvis", "left_hip", "right_hip", "spine1", "left_knee", "right_knee", "spine2",
    "left_ankle", "right_ankle", "spine3", "left_foot", "right_foot", "neck",
    "left_collar", "right_collar", "head", "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow", "left_wrist", "right_wrist", "jaw", "left_eye",
    "right_eye",
    "l_index1", "l_index2", "l_index3", "l_middle1", "l_middle2", "l_middle3",
    "l_pinky1", "l_pinky2", "l_pinky3", "l_ring1", "l_ring2", "l_ring3",
    "l_thumb1", "l_thumb2", "l_thumb3",
    "r_index1", "r_index2", "r_index3", "r_middle1", "r_middle2", "r_middle3",
    "r_pinky1", "r_pinky2", "r_pinky3", "r_ring1", "r_ring2", "r_ring3",
    "r_thumb1", "r_thumb2", "r_thumb3",
]

# Parent -> child edges for the SMPL-X kinematic tree + finger chains
# Covers: root/pelvis, spine chain, neck/head, shoulders/elbows/wrists, all finger chains
_EDGES_CORE: list[tuple[str, str]] = [
    # pelvis/spine
    ("pelvis", "left_hip"), ("pelvis", "right_hip"), ("pelvis", "spine1"),
    ("spine1", "spine2"), ("spine2", "spine3"), ("spine3", "neck"),
    ("spine3", "left_collar"), ("spine3", "right_collar"),
    ("neck", "head"), ("head", "jaw"),
    # legs
    ("left_hip", "left_knee"), ("left_knee", "left_ankle"), ("left_ankle", "left_foot"),
    ("right_hip", "right_knee"), ("right_knee", "right_ankle"), ("right_ankle", "right_foot"),
    # arms
    ("left_collar", "left_shoulder"), ("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"),
    ("right_collar", "right_shoulder"), ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"),
    # left hand fingers (each finger: 3 joints chain from wrist region — approximate via wrist->first phalanx)
    # We connect wrist -> finger base, then along chain
    ("left_wrist", "l_thumb1"), ("l_thumb1", "l_thumb2"), ("l_thumb2", "l_thumb3"),
    ("left_wrist", "l_index1"), ("l_index1", "l_index2"), ("l_index2", "l_index3"),
    ("left_wrist", "l_middle1"), ("l_middle1", "l_middle2"), ("l_middle2", "l_middle3"),
    ("left_wrist", "l_ring1"), ("l_ring1", "l_ring2"), ("l_ring2", "l_ring3"),
    ("left_wrist", "l_pinky1"), ("l_pinky1", "l_pinky2"), ("l_pinky2", "l_pinky3"),
    # right hand
    ("right_wrist", "r_thumb1"), ("r_thumb1", "r_thumb2"), ("r_thumb2", "r_thumb3"),
    ("right_wrist", "r_index1"), ("r_index1", "r_index2"), ("r_index2", "r_index3"),
    ("right_wrist", "r_middle1"), ("r_middle1", "r_middle2"), ("r_middle2", "r_middle3"),
    ("right_wrist", "r_ring1"), ("r_ring1", "r_ring2"), ("r_ring2", "r_ring3"),
    ("right_wrist", "r_pinky1"), ("r_pinky1", "r_pinky2"), ("r_pinky2", "r_pinky3"),
]

_NAME_TO_IDX = {n: i for i, n in enumerate(SMPLX_NAMES)}


def build_edges(joint_names: list[str] | None = None) -> list[tuple[int, int]]:
    """Return edge list as (src_idx, dst_idx) for given joint_names (default SMPL-X 55).

    Filters edges to only those where both endpoints exist in joint_names.
    Extra joints (J>55) are ignored for core topology; they are returned as no edges
    unless caller provides custom edges.
    """
    names = joint_names if joint_names is not None else SMPLX_NAMES
    idx = {n: i for i, n in enumerate(names)}
    edges: list[tuple[int, int]] = []
    for a, b in _EDGES_CORE:
        if a in idx and b in idx:
            edges.append((idx[a], idx[b]))
    return edges


def topology_table(joint_names: list[str] | None = None) -> str:
    names = joint_names if joint_names is not None else SMPLX_NAMES
    edges = build_edges(names)
    lines = [f"J={len(names)}, E={len(edges)}", "idx | joint           | region", "-"*32]
    for i, n in enumerate(names):
        region = _region(n)
        lines.append(f"{i:3d} | {n:<15} | {region}")
    lines.append("-"*32)
    lines.append("edges (src->dst):")
    for s, d in edges:
        lines.append(f"  {names[s]} ({s}) -> {names[d]} ({d})")
    return "\n".join(lines)


def _region(name: str) -> str:
    if name in ("pelvis", "left_hip", "right_hip", "spine1", "spine2", "spine3"):
        return "body/spine"
    if name in ("left_knee", "right_knee", "left_ankle", "right_ankle", "left_foot", "right_foot"):
        return "leg"
    if name in ("neck", "head", "jaw", "left_eye", "right_eye", "left_collar", "right_collar"):
        return "head/neck"
    if "shoulder" in name or "elbow" in name or "wrist" in name:
        return "arm"
    if name.startswith("l_"):
        return "left hand"
    if name.startswith("r_"):
        return "right hand"
    return "unknown"


def joint_label(idx: int, total_j: int) -> tuple[str, str]:
    if idx < len(SMPLX_NAMES):
        return SMPLX_NAMES[idx], _region(SMPLX_NAMES[idx])
    return f"ext_{idx}", "extended (confirm vs config)"
