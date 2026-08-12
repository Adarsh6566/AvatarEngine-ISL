"""Stage 3 — Normalization.

SkeletalMotion -> NormalizedMotion. Makes clips comparable and canonical while
staying avatar-independent (no VRM bones, no retargeting). Steps, in order:

  1. FPS resample   — linear-interp positions, nlerp rotations onto a fixed
                      target-fps timeline, so every clip shares a time base.
  2. Scale normalize— divide all offsets by mean torso length -> unit-torso body,
                      so tall/short signers overlay. Rotations are scale-free.
  3. Root center    — hips placed at the origin every frame (in-place motion).
  4. Canonical facing — yaw-rotate the root so the body faces a fixed forward.
  5. Smooth         — optional moving average (positions) + nlerp mean (rotations).
  6. Trim           — drop leading/trailing idle frames (activity < threshold).

All knobs come from PipelineConfig. Rotations may be None (leaf/occluded) and are
passed through untouched.
"""
from __future__ import annotations

import math

from .config import PipelineConfig
from .models import NormalizedMotion, SkeletalBone, SkeletalFrame, SkeletalMotion

_UP = (0.0, 1.0, 0.0)


def normalize(motion: SkeletalMotion, config: PipelineConfig | None = None) -> NormalizedMotion:
    cfg = config or PipelineConfig()
    frames = [_clone(f) for f in motion.frames]

    frames = _resample(frames, cfg.target_fps)                 # 1
    scale = _apply_scale(frames)                               # 2
    for f in frames:                                           # 3
        f.bones[0].local_position = (0.0, 0.0, 0.0)
    _canonical_facing(frames)                                  # 4
    if cfg.smoothing_window > 1:                               # 5
        frames = _smooth(frames, cfg.smoothing_window)
    trimmed = _trim(frames, cfg.idle_threshold) if cfg.trim else 0  # 6

    n = len(frames)
    for k, f in enumerate(frames):                             # rebase time to 0
        f.t = k / cfg.target_fps
    return NormalizedMotion(
        skeleton=motion.skeleton, fps=cfg.target_fps,
        duration=n / cfg.target_fps if cfg.target_fps else 0.0,
        frames=frames, meta=motion.meta, scale_factor=scale, trimmed_frames=trimmed,
    )


# --- steps -----------------------------------------------------------------


def _resample(frames, fps):
    if len(frames) < 2 or fps <= 0:
        return frames
    t_end = frames[-1].t
    n = max(1, int(round(t_end * fps)))
    out, j = [], 0
    for k in range(n + 1):
        nt = k / fps
        while j < len(frames) - 2 and frames[j + 1].t < nt:
            j += 1
        a, b = frames[j], frames[min(j + 1, len(frames) - 1)]
        span = (b.t - a.t) or 1e-9
        tt = max(0.0, min(1.0, (nt - a.t) / span))
        out.append(SkeletalFrame(nt, [_interp(ba, bb, tt) for ba, bb in zip(a.bones, b.bones)]))
    return out


def _torso(f):
    # torso vector = hips -> chest, stored as the "neck" bone's offset from hips.
    for b in f.bones:
        if b.name == "neck":
            return _mag(b.local_position)
    return 0.0


def _apply_scale(frames):
    lens = [x for x in (_torso(f) for f in frames) if x > 1e-6]
    ref = sum(lens) / len(lens) if lens else 1.0
    scale = 1.0 / ref if ref > 1e-6 else 1.0
    for f in frames:
        for b in f.bones:
            b.local_position = _smul(b.local_position, scale)
    return scale


def _canonical_facing(frames):
    q0 = next((f.bones[0].local_rotation for f in frames if f.bones[0].local_rotation), None)
    if q0 is None:
        return
    fwd = _qrot(q0, (0.0, 0.0, 1.0))
    qc = _q_about_y(-math.atan2(fwd[0], fwd[2]))               # remove yaw
    for f in frames:
        r = f.bones[0].local_rotation
        if r:
            f.bones[0].local_rotation = _qmul(qc, r)


def _smooth(frames, window):
    r = window // 2
    out = []
    for i in range(len(frames)):
        lo, hi = max(0, i - r), min(len(frames), i + r + 1)
        win = frames[lo:hi]
        bones = []
        for bi, b in enumerate(frames[i].bones):
            pos = _vmean([f.bones[bi].local_position for f in win])
            rot = _qmean([f.bones[bi].local_rotation for f in win])
            bones.append(SkeletalBone(b.name, b.parent, pos, rot, b.confidence))
        out.append(SkeletalFrame(frames[i].t, bones))
    return out


def _trim(frames, thr):
    if len(frames) < 3:
        return 0
    act = [0.0] + [sum(_dist(frames[i].bones[k].local_position,
                             frames[i - 1].bones[k].local_position)
                       for k in range(len(frames[i].bones)))
                   for i in range(1, len(frames))]
    start = next((i for i, a in enumerate(act) if a >= thr), 0)
    end = next((i for i in range(len(act) - 1, -1, -1) if act[i] >= thr), len(act) - 1)
    if end - start < 1:
        return 0
    removed = len(frames) - (end - start + 1)
    frames[:] = frames[start:end + 1]
    return removed


# --- math helpers (pure Python; quats are x,y,z,w) -------------------------


def _clone(f):
    return SkeletalFrame(f.t, [SkeletalBone(b.name, b.parent, b.local_position,
                                            b.local_rotation, b.confidence) for b in f.bones])


def _interp(a, b, t):
    rot = _qnlerp(a.local_rotation, b.local_rotation, t)
    return SkeletalBone(a.name, a.parent, _vlerp(a.local_position, b.local_position, t),
                        rot, a.confidence + (b.confidence - a.confidence) * t)


def _sub(a, b): return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
def _smul(v, s): return (v[0]*s, v[1]*s, v[2]*s)
def _mag(v): return math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])
def _dist(a, b): return _mag(_sub(a, b))
def _vlerp(a, b, t): return tuple(a[i] + (b[i]-a[i])*t for i in range(3))
def _vmean(vs): return tuple(sum(v[i] for v in vs)/len(vs) for i in range(3))


def _qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw*bx + ax*bw + ay*bz - az*by,
            aw*by - ax*bz + ay*bw + az*bx,
            aw*bz + ax*by - ay*bx + az*bw,
            aw*bw - ax*bx - ay*by - az*bz)


def _qrot(q, v):
    x, y, z, w = q
    t = (2*(y*v[2]-z*v[1]), 2*(z*v[0]-x*v[2]), 2*(x*v[1]-y*v[0]))
    return (v[0] + w*t[0] + (y*t[2]-z*t[1]),
            v[1] + w*t[1] + (z*t[0]-x*t[2]),
            v[2] + w*t[2] + (x*t[1]-y*t[0]))


def _q_about_y(a):
    return (0.0, math.sin(a/2), 0.0, math.cos(a/2))


def _qnlerp(a, b, t):
    if a is None or b is None:
        return a if b is None else b
    if sum(a[i]*b[i] for i in range(4)) < 0:
        b = tuple(-c for c in b)
    q = tuple(a[i] + (b[i]-a[i])*t for i in range(4))
    n = math.sqrt(sum(c*c for c in q)) or 1.0
    return tuple(c/n for c in q)


def _qmean(qs):
    qs = [q for q in qs if q is not None]
    if not qs:
        return None
    ref, acc = qs[0], [0.0, 0.0, 0.0, 0.0]
    for q in qs:
        if sum(q[i]*ref[i] for i in range(4)) < 0:
            q = tuple(-c for c in q)
        for i in range(4):
            acc[i] += q[i]
    n = math.sqrt(sum(c*c for c in acc)) or 1.0
    return tuple(c/n for c in acc)
