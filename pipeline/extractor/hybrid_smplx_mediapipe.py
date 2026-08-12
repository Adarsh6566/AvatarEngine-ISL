"""
hybrid_smplx_mediapipe — Mode 2: SMPL-X body (shape prior) + MediaPipe hands

Requires local SMPLX assets in pipeline/.models/smplx/. If missing, raises 501.
Per user request: no auto-download, return 501.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from .base import Extractor, Space
from .schemas import CANONICAL_JOINTS, JointSpec, SkeletonStreamDict
from ._smplx_common import check_smplx_available, check_torch_available


class HybridSmplxMediapipeExtractor(Extractor):
    @property
    def name(self) -> str:
        return "hybrid_smplx_mediapipe"

    @property
    def joint_specs(self) -> List[JointSpec]:
        return CANONICAL_JOINTS

    def extract(self, video_path: Path, space: Space = "world") -> SkeletonStreamDict:
        ok, detail = check_smplx_available()
        if not ok:
            raise FileNotFoundError(detail)
        ok_t, tdetail = check_torch_available()
        if not ok_t:
            raise RuntimeError(tdetail)
        # At this point SMPLX is expected to run. For now stub 501 until full impl is vendored.
        # The full implementation needs torch + smplx forward per frame and MediaPipe HandLandmarker anchoring.
        # To keep pipeline/ self-contained without large binaries, we return 501 with instructions.
        raise RuntimeError(
            "SMPL-X body model found but pipeline extractor not yet fully wired (needs torch + smplx forward). "
            f"Found: {detail} | {tdetail}. "
            "This mode is reserved for local SMPL-X — place full checkpoint and request implementation."
        )
