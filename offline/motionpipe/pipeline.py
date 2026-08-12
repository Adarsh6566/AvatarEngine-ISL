"""Orchestrator — the offline counterpart of the runtime Sequencer.

Documents and wires the six stages in order. Every method raises
NotImplementedError; `run` shows the intended data flow. Stages are looked up as
functions/classes from their modules, so the orchestrator holds no stage logic.

    Ingest -> PoseExtraction -> Reconstruction -> Normalization -> Retargeting -> Export
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .config import PipelineConfig
from .models import (
    ClipMeta,
    MotionAsset,
    NormalizedMotion,
    PoseSequence,
    RetargetedMotion,
    SkeletalMotion,
)


@runtime_checkable
class PipelineStage(Protocol):
    """Uniform stage contract: one input model -> one output model.

    Every stage is `run(input, config) -> output`, which is what lets stages be
    listed, swapped, and tested in isolation.
    """

    def run(self, data, config: PipelineConfig): ...


class Pipeline:
    """Runs one dataset through all stages. Skeleton only."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config

    # --- individual stages (each delegates to its module when implemented) ---

    def ingest(self, dataset_dir: str) -> list[ClipMeta]:
        raise NotImplementedError

    def extract_pose(self, meta: ClipMeta) -> PoseSequence:
        raise NotImplementedError

    def reconstruct(self, poses: PoseSequence) -> SkeletalMotion:
        raise NotImplementedError

    def normalize(self, motion: SkeletalMotion) -> NormalizedMotion:
        raise NotImplementedError

    def retarget(self, motion: NormalizedMotion) -> RetargetedMotion:
        raise NotImplementedError

    def export(self, motion: RetargetedMotion, meta: ClipMeta) -> MotionAsset:
        raise NotImplementedError

    # --- full run -----------------------------------------------------------

    def run(self, dataset_dir: str) -> list[MotionAsset]:
        """Ingest a dataset and drive every clip through the chain.

        Intended flow (per clip):
            meta -> extract_pose -> reconstruct -> normalize -> retarget -> export
        Not implemented yet.
        """
        raise NotImplementedError
