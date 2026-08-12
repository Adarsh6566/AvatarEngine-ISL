"""SMPL-X NPZ -> HumanMotionSequence — a REPRESENTATION adapter only.

This converts SMPL-X's REAL 3D joint positions (`smplx_joint_cam`, exported by
offline/colab/export_smplestx_npz.py) into the pipeline's estimator-agnostic
`HumanMotionSequence` (source_motion.v1), so the EXISTING position-based chain
runs unchanged:

    smplx_joint_cam  ->  [this adapter]  ->  HumanMotionSequence
                     ->  source_skeleton -> target_motion -> target_rotations -> vrma

WHAT THIS ADAPTER DOES:  index/name remapping and per-group bucketing ONLY.
WHAT IT DOES NOT DO:     no VRM bone mapping, no IK, no quaternion/rotation solve,
                         no smoothing, no interpolation, no temporal repair, no
                         avatar scaling, no manual rotation math. Positions are
                         copied through verbatim in SMPL-X camera space; a later
                         stage owns any coordinate conversion.

--------------------------------------------------------------------------------
SMPL-X JOINT ORDERING (authoritative — the SMPL-X kinematic tree, joints 0..54).
This is the standard smplx package ordering; `smplx_joint_cam` emits these first,
then extended landmarks (tips/contours) at index >= 55. INDICES MUST BE CONFIRMED
against the first real NPZ's J via the test command before trusting output.

  0  pelvis        9  spine3        18 left_elbow     (hand blocks, 3 per finger)
  1  left_hip      10 left_foot     19 right_elbow    LEFT  25..39:
  2  right_hip     11 right_foot    20 left_wrist       index1/2/3   = 25,26,27
  3  spine1        12 neck          21 right_wrist      middle1/2/3  = 28,29,30
  4  left_knee     13 left_collar   22 jaw              pinky1/2/3   = 31,32,33
  5  right_knee    14 right_collar  23 left_eye         ring1/2/3    = 34,35,36
  6  spine2        15 head          24 right_eye        thumb1/2/3   = 37,38,39
  7  left_ankle    16 left_shoulder                   RIGHT 40..54: same order
  8  right_ankle   17 right_shoulder                    (index..thumb = 40..54)

Note the MANO/SMPL-X finger order is index, middle, PINKY, ring, thumb — pinky
comes BEFORE ring. Do not assume MediaPipe's ordering.
--------------------------------------------------------------------------------
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .source_motion import (
    HumanMotionFrame, HumanMotionMeta, HumanMotionSequence, SourceLandmark, SCHEMA_VERSION,
)

# --- SMPL-X kinematic joint indices (authoritative, joints 0..54) -----------
SMPLX = {
    "pelvis": 0, "left_hip": 1, "right_hip": 2, "left_knee": 4, "right_knee": 5,
    "left_ankle": 7, "right_ankle": 8, "neck": 12, "head": 15,
    "left_shoulder": 16, "right_shoulder": 17, "left_elbow": 18, "right_elbow": 19,
    "left_wrist": 20, "right_wrist": 21,
    # left hand (3 per finger; NO fingertip joint in the core set)
    "l_index1": 25, "l_index2": 26, "l_index3": 27,
    "l_middle1": 28, "l_middle2": 29, "l_middle3": 30,
    "l_pinky1": 31, "l_pinky2": 32, "l_pinky3": 33,
    "l_ring1": 34, "l_ring2": 35, "l_ring3": 36,
    "l_thumb1": 37, "l_thumb2": 38, "l_thumb3": 39,
    "r_index1": 40, "r_index2": 41, "r_index3": 42,
    "r_middle1": 43, "r_middle2": 44, "r_middle3": 45,
    "r_pinky1": 46, "r_pinky2": 47, "r_pinky3": 48,
    "r_ring1": 49, "r_ring2": 50, "r_ring3": 51,
    "r_thumb1": 52, "r_thumb2": 53, "r_thumb3": 54,
}

# --- BODY correspondence -----------------------------------------------------
# source_skeleton.BODY_SPECS reads MediaPipe-Pose indices: 7,8 (ears→head center),
# 11,12 shoulders, 13,14 elbows, 15,16 wrists, 23,24 hips, 25,26 knees, 27,28 ankles.
# Map each to its SMPL-X joint. Ears (7,8): SMPL-X has no ears; BOTH slots reference
# the single SMPL-X head joint, so their midpoint (= source_skeleton's "head") is the
# head centre. This is a NAMING correspondence, not fabricated motion — flagged in
# the report. Unlisted MP body indices are unused downstream (filled zero, conf 0).
BODY_MP_TO_SMPLX = {
    7: "head", 8: "head",                       # ear slots -> head centre (see note)
    11: "left_shoulder", 12: "right_shoulder",
    13: "left_elbow", 14: "right_elbow",
    15: "left_wrist", 16: "right_wrist",
    23: "left_hip", 24: "right_hip",
    25: "left_knee", 26: "right_knee",
    27: "left_ankle", 28: "right_ankle",
}
_MP_BODY_LEN = 33   # MediaPipe Pose landmark count

# --- HAND correspondence -----------------------------------------------------
# source_skeleton hand topology (MediaPipe, 21 landmarks): wrist=0; then per finger
# 4 joints. SMPL-X provides wrist (body joint) + 3 joints per finger and NO fingertip.
# We map the 3 available joints; the fingertip slot (MP idx 4/8/12/16/20) has no SMPL-X
# source in the CORE set -> emitted with confidence 0.0 and position copied from the
# distal joint, and reported as the one coverage gap. If `smplx_joint_cam` turns out
# to include tips (J shows extra hand joints), wire real tip indices here instead.
_MP_HAND_LEN = 21
# (mp_index, smplx_name_suffix or None-for-tip). side prefix added at runtime.
_HAND_MAP = [
    (0, "wrist"),                                     # from body wrist joint
    (1, "thumb1"), (2, "thumb2"), (3, "thumb3"), (4, None),      # thumb CMC/MCP/IP/TIP
    (5, "index1"), (6, "index2"), (7, "index3"), (8, None),
    (9, "middle1"), (10, "middle2"), (11, "middle3"), (12, None),
    (13, "ring1"), (14, "ring2"), (15, "ring3"), (16, None),
    (17, "pinky1"), (18, "pinky2"), (19, "pinky3"), (20, None),
]


def _lm(joints_f, idx):
    """One SMPL-X joint row -> SourceLandmark (positions verbatim, conf 1)."""
    x, y, z = (float(v) for v in joints_f[idx])
    return SourceLandmark(x=x, y=y, z=z, confidence=1.0)


def _zero():
    return SourceLandmark(x=0.0, y=0.0, z=0.0, confidence=0.0)


def _body_row(joints_f) -> list[SourceLandmark]:
    row = [_zero() for _ in range(_MP_BODY_LEN)]
    for mp_idx, name in BODY_MP_TO_SMPLX.items():
        row[mp_idx] = _lm(joints_f, SMPLX[name])
    return row


def _hand_row(joints_f, side: str) -> list[SourceLandmark]:
    p = "l_" if side == "left" else "r_"
    wrist_idx = SMPLX["left_wrist" if side == "left" else "right_wrist"]
    row: list[SourceLandmark] = []
    for mp_idx, suffix in _HAND_MAP:
        if suffix == "wrist":
            row.append(_lm(joints_f, wrist_idx))
        elif suffix is None:                          # fingertip: no core SMPL-X joint
            row.append(_zero())                       # conf 0; distal copy applied below
        else:
            row.append(_lm(joints_f, SMPLX[p + suffix]))
    # Fingertip fallback: copy the finger's distal joint position (conf stays 0 so
    # downstream can see it is not a measured joint). NOT motion invention — a marked
    # placeholder so the 21-slot topology source_skeleton requires is well-formed.
    for tip, distal in ((4, 3), (8, 7), (12, 11), (16, 15), (20, 19)):
        d = row[distal]
        row[tip] = SourceLandmark(x=d.x, y=d.y, z=d.z, confidence=0.0)
    return row


def smplx_npz_to_human_motion(npz_path, gloss: str, source_video: str) -> HumanMotionSequence:
    """Convert an exported SMPL-X NPZ into a HumanMotionSequence (positions only)."""
    data = np.load(npz_path, allow_pickle=True)
    if "smplx_joint_cam" not in data:
        raise KeyError(
            "NPZ has no 'smplx_joint_cam' — re-export with the updated "
            "export_smplestx_npz.py (joint positions are required, not reconstructed)."
        )
    joints = np.asarray(data["smplx_joint_cam"], dtype=np.float32)   # [N,J,3]
    if joints.ndim != 3 or joints.shape[2] != 3:
        raise ValueError(f"smplx_joint_cam must be [N,J,3], got {joints.shape}")
    n, J = joints.shape[0], joints.shape[1]
    max_idx = max(SMPLX.values())
    if J <= max_idx:
        missing = [k for k, v in SMPLX.items() if v >= J]
        raise ValueError(
            f"joint tensor has J={J} but adapter needs index up to {max_idx}. "
            f"Missing SMPL-X joints: {missing}. Confirm smplx_joint_cam ordering."
        )
    fps = float(data["mocap_frame_rate"]) if "mocap_frame_rate" in data else 25.0

    frames: list[HumanMotionFrame] = []
    for i in range(n):
        jf = joints[i]
        frames.append(HumanMotionFrame(
            index=i, timestamp=(i / fps if fps else float(i)),
            body=_body_row(jf), left_hand=_hand_row(jf, "left"),
            right_hand=_hand_row(jf, "right"), face=[],
        ))

    meta = HumanMotionMeta(
        schema=SCHEMA_VERSION, source_video=source_video, gloss=gloss,
        estimator="smplestx@smplx_joint_cam",
        coordinate_space="smplx_camera (X right, Y down/model frame, Z fwd) — verbatim",
        fps=fps, frame_count=n, duration=(n / fps if fps else 0.0),
        landmark_groups={"body": _MP_BODY_LEN, "left_hand": _MP_HAND_LEN,
                         "right_hand": _MP_HAND_LEN, "face": 0},
    )
    return HumanMotionSequence(meta, frames)
