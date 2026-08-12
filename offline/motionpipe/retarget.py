"""Stage 4 — Retargeting.

NormalizedMotion (canonical skeleton) -> RetargetedMotion (a specific rig).

The retargeting ALGORITHM is rig-agnostic: for every canonical bone the profile
maps to a rig bone, it converts the bone's local rotation into the rig's
coordinate frame and copies it onto the rig track; it scales + converts the root
translation. ALL rig-specific knowledge (which bone maps to which, the axis
convention, the target scale, the full rig bone set) lives in the RetargetProfile.
Swapping VRM for SMPL-X/Mixamo means writing another profile — never touching
retarget().
"""
from __future__ import annotations

import math
from typing import Protocol, runtime_checkable

from .models import NormalizedMotion, RetargetedMotion

_IDENTITY = (0.0, 0.0, 0.0, 1.0)


@runtime_checkable
class RetargetProfile(Protocol):
    """Contract for a canonical -> rig mapping. Only bone_map() is required; a
    profile MAY also provide axis_correction(), target_bones(), target_scale."""

    name: str

    def bone_map(self) -> dict[str, str]:
        """Canonical bone name -> rig bone name."""
        ...


class VRMHumanoidProfile:
    """Maps the canonical humanoid skeleton onto VRM humanoid bones."""

    name = "vrm_humanoid"
    target_scale = 1.0               # unit-torso -> rig units (hips translation only)

    def bone_map(self) -> dict[str, str]:
        # Canonical names were chosen humanoid-ish, so most map 1:1 — the point is
        # that the mapping is DATA here, not logic baked into the algorithm.
        return {
            "hips": "hips", "spine": "spine", "neck": "neck",
            "leftUpperArm": "leftUpperArm", "leftLowerArm": "leftLowerArm", "leftHand": "leftHand",
            "rightUpperArm": "rightUpperArm", "rightLowerArm": "rightLowerArm", "rightHand": "rightHand",
            "leftUpperLeg": "leftUpperLeg", "leftLowerLeg": "leftLowerLeg",
            "rightUpperLeg": "rightUpperLeg", "rightLowerLeg": "rightLowerLeg",
        }

    def target_bones(self) -> set[str]:
        """VRM humanoid bones this rig has (core set). Used to report gaps."""
        return {
            "hips", "spine", "chest", "neck", "head",
            "leftShoulder", "leftUpperArm", "leftLowerArm", "leftHand",
            "rightShoulder", "rightUpperArm", "rightLowerArm", "rightHand",
            "leftUpperLeg", "leftLowerLeg", "leftFoot",
            "rightUpperLeg", "rightLowerLeg", "rightFoot",
        }

    def axis_correction(self):
        """Canonical (image-space, Y-down) -> VRM (Y-up): 180° about X (flips Y,Z)."""
        return (1.0, 0.0, 0.0, 0.0)


def retarget(motion: NormalizedMotion, profile: RetargetProfile) -> RetargetedMotion:
    bmap = profile.bone_map()
    axis = getattr(profile, "axis_correction", lambda: _IDENTITY)()
    scale = getattr(profile, "target_scale", 1.0)

    tracks: dict[str, list] = {rig: [] for rig in bmap.values()}
    hips_translation: list = []
    conf_sum, conf_n = 0.0, 0

    for frame in motion.frames:
        bones = {b.name: b for b in frame.bones}
        for canonical, rig in bmap.items():
            b = bones.get(canonical)
            rot = b.local_rotation if b else None
            tracks[rig].append(_convert_rot(rot, axis) if rot else _IDENTITY)
            if b:
                conf_sum += b.confidence
                conf_n += 1
        hips = bones.get("hips")
        pos = _vscale(hips.local_position, scale) if hips else (0.0, 0.0, 0.0)
        hips_translation.append(_qrot(axis, pos))

    return RetargetedMotion(
        target_rig=profile.name, duration=motion.duration, tracks=tracks,
        fps=motion.fps, hips_translation=hips_translation, meta=motion.meta,
        confidence=(conf_sum / conf_n) if conf_n else 0.0,
    )


# --- coordinate conversion + quaternion helpers (x,y,z,w) ------------------


def _convert_rot(q, axis):
    """Re-express rotation q in the rig frame: axis ⊗ q ⊗ axis⁻¹."""
    return _qmul(_qmul(axis, q), _qconj(axis))


def _qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw*bx + ax*bw + ay*bz - az*by,
            aw*by - ax*bz + ay*bw + az*bx,
            aw*bz + ax*by - ay*bx + az*bw,
            aw*bw - ax*bx - ay*by - az*bz)


def _qconj(q):
    return (-q[0], -q[1], -q[2], q[3])


def _qrot(q, v):
    x, y, z, w = q
    t = (2*(y*v[2]-z*v[1]), 2*(z*v[0]-x*v[2]), 2*(x*v[1]-y*v[0]))
    return (v[0] + w*t[0] + (y*t[2]-z*t[1]),
            v[1] + w*t[1] + (z*t[0]-x*t[2]),
            v[2] + w*t[2] + (x*t[1]-y*t[0]))


def _vscale(v, s):
    return (v[0]*s, v[1]*s, v[2]*s)
