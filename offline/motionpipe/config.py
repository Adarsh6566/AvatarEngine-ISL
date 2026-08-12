"""Pipeline configuration.

Externalizes every variable choice so stage logic stays fixed: target fps, which
estimator to use, the canonical skeleton, and the retarget profile. Loaded from
files under offline/config/.

Loader unimplemented in this foundation.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PipelineConfig:
    """Resolved settings for one pipeline run."""

    estimator: str = "mediapipe_holistic"
    target_fps: float = 24.0         # fps to resample to during normalization
    skeleton: str = "canonical_humanoid_v1"
    retarget_profile: str = ""       # profile id (source skeleton -> VRM)
    landmark_set: str = "mp_holistic_v1"
    output_dir: str = "output"
    # --- normalization knobs ---
    smoothing_window: int = 1        # odd frame window; 1 = smoothing off
    idle_threshold: float = 0.01     # per-frame activity (in unit-torso units) below which ends are idle
    trim: bool = True


def load_config(path: str) -> PipelineConfig:
    """Parse a config file into PipelineConfig. Not implemented yet."""
    raise NotImplementedError("config loading is implemented in a later phase")
