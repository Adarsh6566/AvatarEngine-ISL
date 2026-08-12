"""Pose-estimator contract — the pipeline's primary extension point.

A PoseEstimator turns one RGB video into a PoseSequence. Concrete estimators
(MediaPipe, OpenPose, SignAvatars) live in sibling modules and are chosen at
runtime via the registry, so nothing downstream depends on which one ran. Each
estimator is responsible for mapping its native landmark names into the
canonical `landmark_set` declared on the PoseSequence it returns.

No estimator is implemented in this foundation.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import ClipMeta, PoseSequence


@runtime_checkable
class PoseEstimator(Protocol):
    """Contract every pose estimator must satisfy.

    name: stable id used for the registry and stamped onto PoseSequence.estimator
          (include a version, e.g. "mediapipe@0.10").
    estimate: RGB video (+ its ClipMeta) -> per-frame landmarks in the canonical set.
    """

    name: str

    def estimate(self, video_path: str, meta: ClipMeta) -> PoseSequence:
        """Extract landmarks. Implementations do the CV work; not done here."""
        ...
