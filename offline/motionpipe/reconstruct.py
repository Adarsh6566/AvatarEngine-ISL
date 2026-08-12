"""Stage 2 — Motion Reconstruction.

PoseSequence (landmarks) -> SkeletalMotion (canonical skeleton). Avatar-independent:
NO VRM/SMPL-X/Mixamo binding here — just a generic humanoid bone graph with
per-bone local rotations, so any of those rigs can retarget from it later.

Approach (see module docstring in the CLI / README explanation):
  * A bone's global direction = normalize(tail_joint - head_joint).
  * Its LOCAL rotation = shortest-arc quaternion from the PARENT bone's direction
    to this bone's direction (the joint bend). This is swing only.
  * The root (hips) gets an absolute orientation from a hip/spine basis.

Assumptions & limits are documented on BONES and in reconstruct().
No smoothing / normalization / retargeting / export happens here.
"""
from __future__ import annotations

import math

from .models import ClipMeta, PoseFrame, PoseSequence, SkeletalBone, SkeletalFrame, SkeletalMotion

SKELETON = "canonical_humanoid_v1"

# (bone, parent, head_joint, tail_joint). Joint tokens resolve to a landmark key
# or a derived midpoint (MID_HIPS / MID_SHOULDERS / HEAD). Parent-first order so a
# parent's direction is known before its children.
BONES: list[tuple[str, str | None, str, str]] = [
    ("hips",          None,          "MID_HIPS",       "MID_SHOULDERS"),   # root
    ("spine",         "hips",        "MID_HIPS",       "MID_SHOULDERS"),
    ("neck",          "spine",       "MID_SHOULDERS",  "HEAD"),
    ("leftUpperArm",  "spine",       "POSE_LEFT_SHOULDER",  "POSE_LEFT_ELBOW"),
    ("leftLowerArm",  "leftUpperArm","POSE_LEFT_ELBOW",     "POSE_LEFT_WRIST"),
    ("leftHand",      "leftLowerArm","POSE_LEFT_WRIST",     "LEFT_HAND_MIDDLE_FINGER_MCP"),
    ("rightUpperArm", "spine",       "POSE_RIGHT_SHOULDER", "POSE_RIGHT_ELBOW"),
    ("rightLowerArm", "rightUpperArm","POSE_RIGHT_ELBOW",   "POSE_RIGHT_WRIST"),
    ("rightHand",     "rightLowerArm","POSE_RIGHT_WRIST",   "RIGHT_HAND_MIDDLE_FINGER_MCP"),
    ("leftUpperLeg",  "hips",        "POSE_LEFT_HIP",   "POSE_LEFT_KNEE"),
    ("leftLowerLeg",  "leftUpperLeg","POSE_LEFT_KNEE",  "POSE_LEFT_ANKLE"),
    ("rightUpperLeg", "hips",        "POSE_RIGHT_HIP",  "POSE_RIGHT_KNEE"),
    ("rightLowerLeg", "rightUpperLeg","POSE_RIGHT_KNEE","POSE_RIGHT_ANKLE"),
]
# Fallback tails when a hand landmark group is absent in a frame.
_TAIL_FALLBACK = {"LEFT_HAND_MIDDLE_FINGER_MCP": "POSE_LEFT_INDEX",
                  "RIGHT_HAND_MIDDLE_FINGER_MCP": "POSE_RIGHT_INDEX"}


def reconstruct(poses: PoseSequence, config=None) -> SkeletalMotion:
    """Reconstruct a canonical SkeletalMotion from a PoseSequence."""
    frames: list[SkeletalFrame] = []
    conf_sum, conf_n = 0.0, 0

    for pf in poses.frames:
        bones, heads, gdirs, world = [], {}, {}, {}
        for name, parent, head_tok, tail_tok in BONES:
            head = _joint(pf, head_tok)
            tail = _joint(pf, tail_tok) or (_joint(pf, _TAIL_FALLBACK.get(tail_tok, "")) )
            if head is None or tail is None:
                bones.append(SkeletalBone(name, parent, (0.0, 0.0, 0.0), None, 0.0))
                continue

            hp, hc = head
            tp, tc = tail
            heads[name] = hp
            gdirs[name] = _normalize(_sub(tp, hp))
            local_pos = _sub(hp, heads[parent]) if parent in heads else hp

            # Build each bone's WORLD orientation, then express it LOCAL to its
            # parent — local = inverse(parentWorld) * childWorld. The old code
            # wrote a world-space swing (parentDir->childDir) straight into the
            # local slot, which is not a valid hierarchical local rotation.
            if name == "hips":
                world[name] = _hips_rotation(pf)     # absolute root basis
                rot = world[name]
            else:
                world[name] = _world_orient(gdirs[name])
                pw = world.get(parent)
                rot = _qmul(_qconj(pw), world[name]) if (pw and world[name]) else None

            c = min(hc, tc)
            bones.append(SkeletalBone(name, parent, local_pos, rot, c))
            conf_sum += c
            conf_n += 1
        frames.append(SkeletalFrame(t=pf.t, bones=bones))

    return SkeletalMotion(
        skeleton=SKELETON, fps=poses.fps, frames=frames,
        confidence=(conf_sum / conf_n) if conf_n else 0.0, meta=poses.meta,
    )


# --- joint resolution ------------------------------------------------------


def _joint(pf: PoseFrame, token: str):
    """Return (pos, confidence) for a joint token, or None if unavailable."""
    if not token:
        return None
    if token == "MID_HIPS":
        return _midpoint(pf, "POSE_LEFT_HIP", "POSE_RIGHT_HIP")
    if token == "MID_SHOULDERS":
        return _midpoint(pf, "POSE_LEFT_SHOULDER", "POSE_RIGHT_SHOULDER")
    if token == "HEAD":
        token = "POSE_NOSE"
    lm = pf.landmarks.get(token)
    # PoseSequence is MediaPipe image-space (Y-down, +Z into-screen). Convert to
    # canonical world Y-up here — 180° about X: (x, y, z) -> (x, -y, -z). Proper
    # rotation (det +1), so handedness and the algorithm below are unchanged.
    return ((lm.x, -lm.y, -lm.z), lm.confidence) if lm else None


def _midpoint(pf, a, b):
    la, lb = pf.landmarks.get(a), pf.landmarks.get(b)
    if not la or not lb:
        return None
    # Same image-space -> world Y-up conversion as _joint (negate Y and Z).
    return (((la.x + lb.x) / 2, -(la.y + lb.y) / 2, -(la.z + lb.z) / 2),
            min(la.confidence, lb.confidence))


def _hips_rotation(pf):
    """Absolute root orientation from a hip/spine basis, or None if incomplete."""
    hips = _joint(pf, "MID_HIPS")
    chest = _joint(pf, "MID_SHOULDERS")
    lh, rh = pf.landmarks.get("POSE_LEFT_HIP"), pf.landmarks.get("POSE_RIGHT_HIP")
    if not (hips and chest and lh and rh):
        return None
    # hips/chest already come converted via _joint; convert the hip axis the same
    # way (negate Y and Z) so the whole basis is in world Y-up.
    right = _normalize(((rh.x - lh.x), -(rh.y - lh.y), -(rh.z - lh.z)))
    up = _normalize(_sub(chest[0], hips[0]))
    fwd = _normalize(_cross(right, up))
    right = _cross(up, fwd)          # re-orthogonalize
    return _basis_to_quat(right, up, fwd)


# --- tiny vector / quaternion helpers (pure Python, x,y,z,w) ---------------


def _sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _dot(a, b): return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]
def _cross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def _normalize(v):
    n = math.sqrt(_dot(v, v))
    return (v[0]/n, v[1]/n, v[2]/n) if n > 1e-9 else (0.0, 0.0, 0.0)


def _world_orient(d):
    """World orientation whose local +Y axis points along bone direction d.

    Roll is fixed by the world-up reference (not arbitrary): right = up x d, then
    the frame is (right, d, right x-completed). Where d is ~vertical we fall back
    to +Z as the reference so the frame stays well-defined.
    """
    up = (0.0, 1.0, 0.0)
    if abs(_dot(d, up)) > 0.99:
        up = (0.0, 0.0, 1.0)
    right = _normalize(_cross(up, d))
    up2 = _cross(d, right)
    return _basis_to_quat(right, d, up2)   # columns: X->right, Y->d, Z->up2


def _qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw*bx + ax*bw + ay*bz - az*by,
            aw*by - ax*bz + ay*bw + az*bx,
            aw*bz + ax*by - ay*bx + az*bw,
            aw*bw - ax*bx - ay*by - az*bz)


def _qconj(q):
    return (-q[0], -q[1], -q[2], q[3])   # inverse of a unit quaternion


def _from_to(a, b):
    """Shortest-arc quaternion rotating unit vector a onto unit vector b."""
    d = max(-1.0, min(1.0, _dot(a, b)))
    if d > 0.999999:
        return (0.0, 0.0, 0.0, 1.0)
    if d < -0.999999:                       # antiparallel: rotate 180° about any perp axis
        axis = _cross((1.0, 0.0, 0.0), a)
        if _dot(axis, axis) < 1e-6:
            axis = _cross((0.0, 1.0, 0.0), a)
        axis = _normalize(axis)
        return (axis[0], axis[1], axis[2], 0.0)
    axis = _cross(a, b)
    w = 1.0 + d
    q = (axis[0], axis[1], axis[2], w)
    n = math.sqrt(sum(c*c for c in q))
    return tuple(c/n for c in q)


def _basis_to_quat(right, up, fwd):
    """3x3 rotation (columns = right/up/fwd) -> quaternion (x,y,z,w)."""
    m00, m11, m22 = right[0], up[1], fwd[2]
    tr = m00 + m11 + m22
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w = 0.25 * s
        x = (up[2] - fwd[1]) / s
        y = (fwd[0] - right[2]) / s
        z = (right[1] - up[0]) / s
    else:
        # fall back to the largest diagonal term for numerical stability
        x = (up[2] - fwd[1]); y = (fwd[0] - right[2]); z = (right[1] - up[0])
        n = math.sqrt(x*x + y*y + z*z) or 1.0
        return (x/n, y/n, z/n, 0.0)
    n = math.sqrt(x*x + y*y + z*z + w*w) or 1.0
    return (x/n, y/n, z/n, w/n)
