"""
Schemas — Pydantic mirror of frontend/skeleton/SkeletonStream.ts source_skeleton.v1.
Kept inside pipeline/ so we never touch root files.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, Field

JointValue = Optional[Tuple[float, float, float, float]]  # [x,y,z,conf] or null
JointsMap = Dict[str, JointValue]


class JointSpec(BaseModel):
    name: str
    parent: Optional[str] = None


class SkeletonFrame(BaseModel):
    index: int
    timestamp: float
    joints: JointsMap


class SkeletonMeta(BaseModel):
    schema_: str = Field(alias="schema", default="source_skeleton.v1")
    space: str = "unknown"
    fps: float
    frameCount: int
    duration: float
    joints: List[JointSpec]
    # provenance
    source_video: Optional[str] = None
    estimator: Optional[str] = None
    gloss: Optional[str] = None
    coordinate_space: Optional[str] = None


class SkeletonStreamDict(BaseModel):
    """Exact shape written to outputs/*.json — mirrors source_skeleton.v1 meta+frames."""

    meta: SkeletonMeta
    frames: List[SkeletonFrame]

    def to_view_dict(self) -> dict:
        """Serialize with 'schema' key (not schema_)."""
        d = self.model_dump(by_alias=True)
        return d


# ---------------------------------------------------------------------------
# Canonical joint hierarchy — rig-mappable, shared by all extractors.
# Names match the project's toViewSpace expectations (hips is root).
# Extend without breaking: append, never rename.
# ---------------------------------------------------------------------------

CANONICAL_JOINTS: List[JointSpec] = [
    JointSpec(name="hips", parent=None),
    JointSpec(name="spine", parent="hips"),
    JointSpec(name="chest", parent="spine"),
    JointSpec(name="neck", parent="chest"),
    JointSpec(name="head", parent="neck"),
    # left arm
    JointSpec(name="lShoulder", parent="chest"),
    JointSpec(name="lElbow", parent="lShoulder"),
    JointSpec(name="lWrist", parent="lElbow"),
    JointSpec(name="lHand", parent="lWrist"),
    # left hand fingers — 4 joints/finger (MCP, PIP, DIP, TIP): 1→2 drives the
    # proximal bone, 2→3 the intermediate, 3→4 the distal. Thumb uses its 3 points
    # (MCP, IP, TIP) to drive proximal + distal. See mediapipe_extractor landmark map.
    JointSpec(name="lThumb1", parent="lHand"),
    JointSpec(name="lThumb2", parent="lThumb1"),
    JointSpec(name="lThumb3", parent="lThumb2"),
    JointSpec(name="lIndex1", parent="lHand"),
    JointSpec(name="lIndex2", parent="lIndex1"),
    JointSpec(name="lIndex3", parent="lIndex2"),
    JointSpec(name="lIndex4", parent="lIndex3"),
    JointSpec(name="lMiddle1", parent="lHand"),
    JointSpec(name="lMiddle2", parent="lMiddle1"),
    JointSpec(name="lMiddle3", parent="lMiddle2"),
    JointSpec(name="lMiddle4", parent="lMiddle3"),
    JointSpec(name="lRing1", parent="lHand"),
    JointSpec(name="lRing2", parent="lRing1"),
    JointSpec(name="lRing3", parent="lRing2"),
    JointSpec(name="lRing4", parent="lRing3"),
    JointSpec(name="lPinky1", parent="lHand"),
    JointSpec(name="lPinky2", parent="lPinky1"),
    JointSpec(name="lPinky3", parent="lPinky2"),
    JointSpec(name="lPinky4", parent="lPinky3"),
    # right arm
    JointSpec(name="rShoulder", parent="chest"),
    JointSpec(name="rElbow", parent="rShoulder"),
    JointSpec(name="rWrist", parent="rElbow"),
    JointSpec(name="rHand", parent="rWrist"),
    JointSpec(name="rThumb1", parent="rHand"),
    JointSpec(name="rThumb2", parent="rThumb1"),
    JointSpec(name="rThumb3", parent="rThumb2"),
    JointSpec(name="rIndex1", parent="rHand"),
    JointSpec(name="rIndex2", parent="rIndex1"),
    JointSpec(name="rIndex3", parent="rIndex2"),
    JointSpec(name="rIndex4", parent="rIndex3"),
    JointSpec(name="rMiddle1", parent="rHand"),
    JointSpec(name="rMiddle2", parent="rMiddle1"),
    JointSpec(name="rMiddle3", parent="rMiddle2"),
    JointSpec(name="rMiddle4", parent="rMiddle3"),
    JointSpec(name="rRing1", parent="rHand"),
    JointSpec(name="rRing2", parent="rRing1"),
    JointSpec(name="rRing3", parent="rRing2"),
    JointSpec(name="rRing4", parent="rRing3"),
    JointSpec(name="rPinky1", parent="rHand"),
    JointSpec(name="rPinky2", parent="rPinky1"),
    JointSpec(name="rPinky3", parent="rPinky2"),
    JointSpec(name="rPinky4", parent="rPinky3"),
    # legs (optional, aids root scale + whole-body)
    JointSpec(name="lHip", parent="hips"),
    JointSpec(name="lKnee", parent="lHip"),
    JointSpec(name="lAnkle", parent="lKnee"),
    JointSpec(name="lFoot", parent="lAnkle"),
    JointSpec(name="rHip", parent="hips"),
    JointSpec(name="rKnee", parent="rHip"),
    JointSpec(name="rAnkle", parent="rKnee"),
    JointSpec(name="rFoot", parent="rAnkle"),
]

# Edges are derived from parent links — same as frontend streamEdges()
CANONICAL_EDGES: List[Tuple[str, str]] = [
    (j.parent, j.name) for j in CANONICAL_JOINTS if j.parent is not None  # type: ignore
]
