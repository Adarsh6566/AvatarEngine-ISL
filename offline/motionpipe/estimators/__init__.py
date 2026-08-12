"""Pluggable pose estimators.

Public contract: `base.PoseEstimator`. Selection: `registry`. Concrete
estimators (mediapipe.py, openpose.py, signavatars.py) are added later and
self-register on import — none exist yet.
"""
from .base import PoseEstimator
from . import registry

__all__ = ["PoseEstimator", "registry"]
