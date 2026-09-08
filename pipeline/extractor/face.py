"""Facial expression capture, as blendshape coefficients per frame.

In sign language the face is grammar, not decoration: brow raise marks a
yes/no question, brow furrow marks a wh-question, and mouth shapes carry
adverbial meaning. The body pipeline captured none of it — hands and joints
only — so every sign in the library performs with a blank face.

This closes that gap from the SAME footage the body came from, which matters:
the expression a sign is given is then the one its signer actually made, at the
frame they made it, rather than one inferred afterwards from the word.

WHY A CROP IS REQUIRED
----------------------
Running MediaPipe's face landmarker on the full frame finds nothing. Measured
on the ISL greetings clips: 0 of 14 sampled frames. The face occupies about
120px of a 1920x1080 frame — roughly 10% of its height — and the detector
downscales its input before searching, which leaves the face far too small to
find. Cropping to the head using the body keypoints already available, then
upscaling, takes the same clips to 14 of 14.

WHAT SURVIVES AT THIS RESOLUTION
--------------------------------
Coarse, high-amplitude movement does; fine detail does not. Measured across
four takes each of two signs, brow raise and smile repeat closely (browInnerUp
0.61/0.62/0.59, mouthSmile 0.79/0.82/0.85) while mouthPucker appeared in one
take of four and was absent in the rest — noise, not a mouth morpheme.

That split is the fortunate one: brow raise and brow furrow are exactly the
markers carrying question grammar. Callers averaging across takes should gate
on cross-take agreement rather than trusting every coefficient.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, Optional, Sequence

_LANDMARKER = None
_MP = None
_UNAVAILABLE: Optional[str] = None

# Upscaled crop size handed to the landmarker. 512 is comfortably above the
# model's own working resolution, so the crop is never the limiting factor —
# the ~120px of real pixels in the source is.
CROP_SIZE = 512

# How much bigger than the eye/ear span to make the crop. The body keypoints
# only bracket eyes and ears, which is the middle of the face; this pads out to
# forehead and chin so brows and jaw are inside the crop rather than clipped by
# its edge.
CROP_SCALE = 2.6


def _load():
    """Lazy singleton. The model is ~3.6MB and loading it costs real time."""
    global _LANDMARKER, _MP, _UNAVAILABLE
    if _LANDMARKER is not None or _UNAVAILABLE is not None:
        return _LANDMARKER, _MP

    model = Path(__file__).parent.parent / ".models" / "face_landmarker.task"
    if not model.exists():
        _UNAVAILABLE = f"face_landmarker.task not found at {model}"
        return None, None
    try:
        import mediapipe as mp
        from mediapipe.tasks.python.core.base_options import BaseOptions
        from mediapipe.tasks.python.vision.core.vision_task_running_mode import (
            VisionTaskRunningMode,
        )
        from mediapipe.tasks.python.vision.face_landmarker import (
            FaceLandmarker,
            FaceLandmarkerOptions,
        )

        _LANDMARKER = FaceLandmarker.create_from_options(
            FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(model)),
                output_face_blendshapes=True,
                num_faces=1,
                # Lowered from the 0.5 default. The input is an upscaled crop of
                # a small face, so the detector is working from softer evidence
                # than it would on a portrait; at 0.5 it rejects usable frames.
                min_face_detection_confidence=0.3,
                min_face_presence_confidence=0.3,
                running_mode=VisionTaskRunningMode.IMAGE,
            )
        )
        _MP = mp
    except Exception as e:  # pragma: no cover - depends on local install
        _UNAVAILABLE = f"{type(e).__name__}: {e}"
        return None, None
    return _LANDMARKER, _MP


def unavailable_reason() -> Optional[str]:
    """Why face capture is off, or None when it is working."""
    _load()
    return _UNAVAILABLE


def face_box(points: Sequence[Optional[Sequence[float]]], width: int, height: int):
    """A square crop around the head, from whatever face keypoints exist.

    `points` are the body estimator's head keypoints in pixels — for YOLO's
    COCO layout that is nose, eyes and ears (indices 0-4). Returns None when
    too few were found to locate a head at all.
    """
    xs = [float(p[0]) for p in points if p is not None]
    ys = [float(p[1]) for p in points if p is not None]
    if len(xs) < 2:
        return None

    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    side = max(max(xs) - min(xs), max(ys) - min(ys)) * CROP_SCALE
    if not math.isfinite(side) or side < 8:
        return None

    x0 = int(max(0, cx - side / 2))
    y0 = int(max(0, cy - side / 2))
    x1 = int(min(width, cx + side / 2))
    y1 = int(min(height, cy + side / 2))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    return x0, y0, x1, y1


def blendshapes(frame, head_points: Sequence[Optional[Sequence[float]]]) -> Optional[Dict[str, float]]:
    """52 blendshape coefficients for one BGR frame, or None if no face.

    Returning None rather than zeros is deliberate: a frame where the face was
    not found is not a frame where the face was neutral, and an averaging step
    needs to be able to tell those apart.
    """
    landmarker, mp = _load()
    if landmarker is None or mp is None:
        return None

    try:
        import cv2
    except Exception:
        return None

    h, w = frame.shape[:2]
    box = face_box(head_points, w, h)
    if box is None:
        return None
    x0, y0, x1, y1 = box

    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    crop = cv2.resize(crop, (CROP_SIZE, CROP_SIZE), interpolation=cv2.INTER_CUBIC)

    try:
        image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=cv2.cvtColor(crop, cv2.COLOR_BGR2RGB),
        )
        result = landmarker.detect(image)
    except Exception:
        return None

    if not result.face_blendshapes:
        return None
    # _neutral is the model's own "no expression" category and carries no
    # information a consumer can use; every other coefficient is relative to it.
    return {
        c.category_name: round(float(c.score), 4)
        for c in result.face_blendshapes[0]
        if c.category_name != "_neutral"
    }
