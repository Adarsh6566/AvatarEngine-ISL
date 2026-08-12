"""Per-joint temporal smoothing with deadzone — fixes spine jitter while keeping hands accurate."""

from __future__ import annotations

import math
from typing import Dict, Tuple

from .schemas import SkeletonStreamDict, SkeletonFrame

JointVal = Tuple[float, float, float, float] | None

# joint → (alpha, deadzone)  alpha=1 = no smoothing, 0 = frozen
# Stable: spine/hips/head/legs need heavy smoothing + larger deadzone
# Fine: fingers need almost no smoothing
PRESETS: Dict[str, Tuple[float, float]] = {}

STABLE = ["hips", "spine", "chest", "neck", "head", "lHip", "rHip", "lKnee", "rKnee", "lAnkle", "rAnkle", "lFoot", "rFoot"]
SEMI = ["lShoulder", "rShoulder"]
MOBILE = ["lElbow", "rElbow", "lWrist", "rWrist"]
FINE = ["lHand", "rHand", "lThumb1", "lThumb2", "lIndex1", "lIndex2", "lMiddle1", "lMiddle2", "lRing1", "lRing2", "lPinky1", "lPinky2",
        "rThumb1", "rThumb2", "rIndex1", "rIndex2", "rMiddle1", "rMiddle2", "rRing1", "rRing2", "rPinky1", "rPinky2"]

for j in STABLE:
    PRESETS[j] = (0.22, 0.004)  # heavy EMA, tiny deadzone — no hold-then-snap
for j in SEMI:
    PRESETS[j] = (0.35, 0.006)
for j in MOBILE:
    PRESETS[j] = (0.55, 0.004)
for j in FINE:
    PRESETS[j] = (0.85, 0.002)  # almost raw

# abrupt change thresholds — if delta > this, treat as blurry-frame jump and smooth more heavily
ABRUPT_THRESH: Dict[str, float] = {}
for j in STABLE:
    ABRUPT_THRESH[j] = 0.08
for j in SEMI:
    ABRUPT_THRESH[j] = 0.10
for j in MOBILE:
    ABRUPT_THRESH[j] = 0.12
for j in FINE:
    ABRUPT_THRESH[j] = 0.15

DEFAULT = (0.35, 0.010)
DEFAULT_ABRUPT = 0.12


def _dist(a: JointVal, b: JointVal) -> float:
    if a is None or b is None:
        return 999.0
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)


def smooth_stream(stream: SkeletonStreamDict) -> SkeletonStreamDict:
    """Return new stream with per-joint EMA + deadzone. First frame passes through."""
    if not stream.frames:
        return stream

    prev: Dict[str, JointVal] = {}
    new_frames = []

    for f in stream.frames:
        out_joints: Dict[str, JointVal] = {}
        for name, cur in f.joints.items():
            alpha, deadzone = PRESETS.get(name, DEFAULT)
            prv = prev.get(name)

            if cur is None:
                # keep as None for gap — second pass will linearly interpolate across blurry gap
                out_joints[name] = None
                # do not update prev (keep last real for next valid)
                continue

            if prv is None:
                out_joints[name] = cur
                prev[name] = cur
                continue

            d = _dist(prv, cur)
            abrupt = ABRUPT_THRESH.get(name, DEFAULT_ABRUPT)
            # if abrupt jump (blurry gap), interpolate: stable -> heavy smooth, fine -> keep responsive
            use_alpha = alpha
            if d > abrupt:
                if name in FINE:
                    use_alpha = min(alpha, 0.45)  # hands stay accurate even on abrupt
                elif name in MOBILE:
                    use_alpha = min(alpha, 0.25)
                else:
                    use_alpha = min(alpha, 0.12)  # stable heavy smooth
            if d < deadzone:
                # within allowance — keep previous to kill jitter
                out_joints[name] = prv
                # slowly drift prev toward cur to avoid stuck
                # tiny nudge: 5% of delta
                nx = prv[0] + (cur[0]-prv[0])*0.05
                ny = prv[1] + (cur[1]-prv[1])*0.05
                nz = prv[2] + (cur[2]-prv[2])*0.05
                prev[name] = (nx, ny, nz, cur[3])
            else:
                # EMA with possibly reduced alpha for abrupt
                nx = prv[0]*(1-use_alpha) + cur[0]*use_alpha
                ny = prv[1]*(1-use_alpha) + cur[1]*use_alpha
                nz = prv[2]*(1-use_alpha) + cur[2]*use_alpha
                smoothed = (nx, ny, nz, cur[3])
                out_joints[name] = smoothed
                prev[name] = smoothed

        # fix spine bending forward: vertical chain should be Z≈0 (upright facing camera)
        # damp Z for spine/hips/chest/neck/head heavily toward 0 — keeps spine vertical, prevents forward lean from shoulder Z
        for vname in ["hips", "spine", "chest", "neck", "head"]:
            v = out_joints.get(vname)
            if v is not None:
                # keep X,Y as smoothed, force Z toward 0 with 90% damping
                out_joints[vname] = (v[0], v[1], v[2]*0.12, v[3])
        new_frames.append(SkeletonFrame(index=f.index, timestamp=f.timestamp, joints=out_joints))

    # second pass: fill blurry-frame gaps (consecutive None) with linear interpolation
    # this makes abrupt re-appearances become smooth ramps over gap length
    MAX_GAP = 12  # interpolate up to 12 frames (~0.4s @30fps) of blur
    for joint_name in [j.name for j in stream.meta.joints]:
        # collect valid indices and values
        valid = [(i, f.joints.get(joint_name)) for i, f in enumerate(new_frames) if f.joints.get(joint_name) is not None]
        if len(valid) < 2:
            continue
        for k in range(len(valid)-1):
            i0, v0 = valid[k]
            i1, v1 = valid[k+1]
            gap = i1 - i0 - 1
            if 1 <= gap <= MAX_GAP:
                for g in range(1, gap+1):
                    alpha = g / (gap+1)
                    interp = (
                        v0[0]*(1-alpha) + v1[0]*alpha,
                        v0[1]*(1-alpha) + v1[1]*alpha,
                        v0[2]*(1-alpha) + v1[2]*alpha,
                        max(v0[3], v1[3]),
                    )
                    # replace None with interp in gap frames
                    jf = new_frames[i0+g]
                    # need to copy joints dict (create new Frame)
                    new_joints = dict(jf.joints)
                    new_joints[joint_name] = interp
                    new_frames[i0+g] = SkeletonFrame(index=jf.index, timestamp=jf.timestamp, joints=new_joints)

    meta = stream.meta.model_copy()
    # tag estimator
    if "smoothed" not in (meta.estimator or ""):
        meta.estimator = (meta.estimator or "") + " + smoothed"
    return SkeletonStreamDict(meta=meta, frames=new_frames)
