"""
Normalize — Python mirror of frontend/skeleton/SkeletonStream.ts:toViewSpace().

Does exactly one thing: Y-flip for Y-down sources, root-center at hips per frame,
unit-scale so mean hip→head distance = 1. This is the single normalization point.
"""

from __future__ import annotations

import math
from typing import List

from .schemas import SkeletonFrame, SkeletonStreamDict

ROOT = "hips"
UP = "head"
UP_FALLBACK = "chest"


def to_view_space(stream: SkeletonStreamDict) -> SkeletonStreamDict:
    flip_y = "Y down" in (stream.meta.space or "") or "image" in (stream.meta.space or "").lower()
    # mediapipe world Z is mirrored vs Three.js right-handed: flip Z for world to un-mirror upper body
    flip_z = "world" in (stream.meta.space or "").lower()

    # mean hip→head length
    lens: List[float] = []
    for f in stream.frames:
        a = f.joints.get(ROOT)
        b = f.joints.get(UP) or f.joints.get(UP_FALLBACK)
        if a and b:
            lens.append(math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2))
    mean = sum(lens) / len(lens) if lens else 1.0
    scale = 1.0 / mean if mean > 1e-6 else 1.0

    frames: List[SkeletonFrame] = []
    for f in stream.frames:
        root = f.joints.get(ROOT) or (0.0, 0.0, 0.0, 0.0)
        rx, ry, rz = root[0], root[1], root[2]
        joints = {}
        for name, v in f.joints.items():
            if v is None:
                joints[name] = None
                continue
            x, y, z, c = v
            nx = (x - rx) * scale
            ny = ((ry - y) * scale if flip_y else (y - ry) * scale)
            # flip Z for world to fix mirrored upper body (mediapipe left-handed vs Three right-handed)
            nz = ((rz - z) * scale if flip_z else (z - rz) * scale)
            joints[name] = (nx, ny, nz, c)
        frames.append(SkeletonFrame(index=f.index, timestamp=f.timestamp, joints=joints))

    # rebuild meta with view space label
    meta = stream.meta.model_copy()
    meta.space = "view (Y-up, root-centered at hips, unit = mean hip→head)"
    meta.coordinate_space = stream.meta.space
    # schema tag
    meta.schema_ = f"{stream.meta.schema_} → view"

    return SkeletonStreamDict(meta=meta, frames=frames)
