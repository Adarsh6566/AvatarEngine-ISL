"""Quality evaluation — the spike's validation gate.

Responsibility: score a produced motion so we can answer "is video -> avatar
motion good enough?" objectively, and catch regressions as stages improve.
Input : any stage artifact (PoseSequence / SkeletalMotion / RetargetedMotion)
Output: a metrics dict (e.g. tracking confidence, jitter, bone-length drift,
        duration sanity) — plus, ultimately, a human/native-signer verdict.
Owner : this module.

No metrics implemented here.
"""
from __future__ import annotations

from typing import Any


def evaluate(artifact: Any) -> dict[str, float]:
    """Compute quality metrics for a stage artifact. Not implemented yet."""
    raise NotImplementedError
