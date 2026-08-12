"""HumanMotionSequence — the new SOURCE motion representation (schema v1).

The full temporal MediaPipe capture, grouped into body / left_hand / right_hand /
face, preserving EVERY landmark and its confidence. NO reduction to bones, NO
rotation math, NO resample/smooth/trim/normalize. This is the raw observed motion
that later stages (skeleton mapping / retargeting) will consume.

Kept separate from the old models.py / SkeletalMotion path, which stays intact as
the migration baseline.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

SCHEMA_VERSION = "human_motion.v1"

# MediaPipe Holistic groups, matched by the key prefix the estimator emits.
_GROUPS = (("body", "POSE_"), ("left_hand", "LEFT_HAND_"),
           ("right_hand", "RIGHT_HAND_"), ("face", "FACE_"))


@dataclass
class SourceLandmark:
    x: float
    y: float
    z: float
    confidence: float          # MediaPipe visibility (pose) or presence proxy


@dataclass
class HumanMotionFrame:
    index: int
    timestamp: float           # seconds from clip start (source fps, not resampled)
    body: list[SourceLandmark]
    left_hand: list[SourceLandmark]
    right_hand: list[SourceLandmark]
    face: list[SourceLandmark]


@dataclass
class HumanMotionMeta:
    schema: str
    source_video: str
    gloss: str
    estimator: str
    coordinate_space: str      # e.g. "normalized" (MediaPipe image-normalized, Y-down)
    fps: float
    frame_count: int
    duration: float
    landmark_groups: dict      # max landmarks seen per group, e.g. {"body":33,...}


@dataclass
class HumanMotionSequence:
    meta: HumanMotionMeta
    frames: list[HumanMotionFrame]


def from_pose_sequence(ps, gloss: str, source_video: str) -> HumanMotionSequence:
    """Regroup a captured PoseSequence (flat landmark dict) into grouped source
    motion. Preserves per-group landmark order and every value; performs no math."""
    frames: list[HumanMotionFrame] = []
    for i, pf in enumerate(ps.frames):
        buckets = {g: [] for g, _ in _GROUPS}
        for key, lm in pf.landmarks.items():       # insertion order == MediaPipe index order
            for g, pre in _GROUPS:
                if key.startswith(pre):
                    buckets[g].append(SourceLandmark(lm.x, lm.y, lm.z, lm.confidence))
                    break
        frames.append(HumanMotionFrame(i, pf.t, buckets["body"], buckets["left_hand"],
                                       buckets["right_hand"], buckets["face"]))

    groups = {g: max((len(getattr(f, g)) for f in frames), default=0) for g, _ in _GROUPS}
    meta = HumanMotionMeta(
        schema=SCHEMA_VERSION, source_video=source_video, gloss=gloss,
        estimator=ps.estimator, coordinate_space=ps.space, fps=ps.fps,
        frame_count=len(frames),
        duration=(len(frames) / ps.fps if ps.fps else 0.0),
        landmark_groups=groups,
    )
    return HumanMotionSequence(meta, frames)


def to_dict(seq: HumanMotionSequence) -> dict:
    return asdict(seq)
