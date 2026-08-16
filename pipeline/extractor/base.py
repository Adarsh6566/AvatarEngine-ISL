"""Extractor ABC — one interface for all skeletons (2D image or 3D world)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

from .schemas import JointSpec, SkeletonStreamDict

Space = Literal["image", "world"]


class Extractor(ABC):
    """Implement extract() to return a source_skeleton.v1 dict."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def joint_specs(self) -> list[JointSpec]: ...

    @abstractmethod
    def extract(self, video_path: Path, space: Space = "world") -> SkeletonStreamDict: ...

    def probe_estimator_label(self, space: Space) -> str:
        return f"{self.name} ({space})"
