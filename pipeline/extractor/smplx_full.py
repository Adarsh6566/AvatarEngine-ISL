"""
smplx_full — Mode 3: Complete SMPL-X (body + MANO hands + FLAME face)

Requires local SMPLX assets in pipeline/.models/smplx/. No auto-download.
If missing, raises 501 per user request.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from .base import Extractor, Space
from .schemas import CANONICAL_JOINTS, JointSpec, SkeletonStreamDict
from ._smplx_common import check_smplx_available, check_torch_available


class SmplxFullExtractor(Extractor):
    @property
    def name(self) -> str:
        return "smplx_full"

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
        raise RuntimeError(
            "Complete SMPL-X (body+MANO+FLAME) requires full SMPLX pipeline (torch + smplx + mano). "
            f"Found: {detail} | {tdetail}. "
            "Place SMPLX_* and MANO checkpoints in pipeline/.models/smplx/ and request wiring."
        )
