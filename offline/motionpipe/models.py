"""Data contracts that flow between pipeline stages.

Fields only — no processing logic. Each model is the serialized artifact at one
stage boundary (see DESIGN.md). Numeric arrays are typed loosely (list/tuple)
to keep the foundation dependency-free; implementations may swap to np.ndarray.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --- Input -----------------------------------------------------------------


@dataclass
class ClipMeta:
    """One source video and its provenance.

    Populated by ingest.py from the file tree. Discovery fields (label + paths)
    are always set; capture metadata (fps/duration/resolution) is best-effort —
    None when no probe tool (ffprobe) is available — and provenance defaults to
    blank until a dataset manifest supplies it. `gloss` IS the sign label.
    """

    gloss: str                       # sign label from the parent dir, e.g. "HELLO"
    clip_id: str                     # unique id: dataset-relative path without extension
    filename: str                    # e.g. "hello_01.mp4"
    source_path: str                 # absolute path to the video
    dataset: str                     # top-level dataset folder, e.g. "isl_greeting"

    # Best-effort capture metadata (None when no probe tool is available).
    fps: float | None = None
    frame_count: int | None = None
    duration: float | None = None    # seconds
    resolution: tuple[int, int] | None = None  # (width, height)

    # Provenance — blank until a dataset manifest provides it.
    signer_id: str = ""
    consent_ref: str = ""
    license: str = ""
    dataset_version: str = ""
    handedness: str = "right"
    notes: str = ""


# --- After pose extraction -------------------------------------------------


@dataclass
class Landmark:
    """One tracked point in a single frame."""

    name: str                        # canonical landmark name
    x: float
    y: float
    z: float
    confidence: float


@dataclass
class PoseFrame:
    t: float                         # seconds from clip start
    landmarks: dict[str, Landmark]


@dataclass
class PoseSequence:
    """Per-frame landmarks for one clip, tagged with its estimator."""

    landmark_set: str                # canonical taxonomy id (estimators map into this)
    estimator: str                   # "mediapipe@x.y", "openpose@…", "signavatars@…"
    fps: float
    space: str                       # "image" | "normalized" | "world"
    frames: list[PoseFrame]
    meta: ClipMeta


# --- After reconstruction / normalization ----------------------------------

Quaternion = tuple[float, float, float, float]
Vec3 = tuple[float, float, float]


@dataclass
class SkeletalBone:
    """One bone's pose in one frame, in the canonical (avatar-independent) skeleton."""

    name: str
    parent: str | None               # None for the root (hips)
    local_position: Vec3             # offset from the parent joint, in input space
    # (x,y,z,w) rotation LOCAL to the parent bone = inverse(parentWorld)*childWorld,
    # in the canonical Y-up frame (canonical rest = identity). Root (hips) holds its
    # absolute world orientation. None when not inferable (leaf/occluded).
    local_rotation: Quaternion | None
    confidence: float                # min of the endpoint landmark confidences, 0..1


@dataclass
class SkeletalFrame:
    t: float                         # seconds from clip start
    bones: list[SkeletalBone]


@dataclass
class SkeletalMotion:
    """Reconstructed motion on a canonical skeleton (estimator- and rig-agnostic)."""

    skeleton: str                    # canonical skeleton id, e.g. "canonical_humanoid_v1"
    fps: float
    frames: list[SkeletalFrame]
    confidence: float                # aggregate reconstruction quality 0..1
    meta: ClipMeta


@dataclass
class NormalizedMotion:
    """Canonicalized SkeletalMotion: fixed fps, normalized scale/facing, trimmed."""

    skeleton: str
    fps: float
    duration: float                  # seconds, after trimming to the sign span
    frames: list[SkeletalFrame]
    meta: ClipMeta
    scale_factor: float = 1.0        # multiplier applied to normalize body scale
    trimmed_frames: int = 0          # idle frames removed from the ends


# --- After retargeting -----------------------------------------------------


@dataclass
class RetargetedMotion:
    """Motion expressed on the VRM humanoid rig, ready to export as VRMA."""

    target_rig: str                  # e.g. "vrm_humanoid"
    duration: float
    tracks: dict[str, list[Quaternion]]  # rig bone name -> per-frame rotation
    fps: float
    hips_translation: list[Vec3] | None
    meta: ClipMeta
    confidence: float = 0.0          # mean confidence of the mapped bones, 0..1


# --- Output ----------------------------------------------------------------


@dataclass
class ManifestFragment:
    """A motion_manifest.json entry — schema-identical to the runtime's, so it
    is a drop-in merge (never auto-applied)."""

    id: str                          # gloss token, e.g. "HELLO"
    motionId: str                    # dataset-scoped id, e.g. "video_hello"
    assetPath: str                   # "/animations/hello_isl.vrma"
    duration: float
    dataset: str = "video"           # discriminator DatasetLoader routes on
    provenance: dict = field(default_factory=dict)  # dataset_version, clip_ids, signer, license


@dataclass
class MotionAsset:
    """Final output: a written .vrma plus its manifest fragment."""

    vrma_path: str
    fragment: ManifestFragment
