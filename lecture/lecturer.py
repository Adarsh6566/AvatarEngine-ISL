"""Find the lecturer in a video and cut them out of it.

The eventual plan is to sign with the lecturer's own likeness rather than a
stock avatar, which removes the proportion mismatch that makes a borrowed
skeleton clip through its own body: their arms are already the right length for
their torso, because they are their arms.

This is the first step of that and only that — locating the person and taking a
clean still of them. Turning a still into something that can be posed is a
separate and much larger problem.

The frame is chosen, not taken at random. A lecture opens on a title card and
closes on a summary as often as not, so the best frame is the one where the
detector is most confident it is looking at a whole person.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class LecturerShot:
    """A still of the lecturer, and where it came from."""

    frame_index: int
    timestamp: float
    confidence: float
    box: tuple[int, int, int, int]  # x, y, w, h in the source frame
    image: np.ndarray  # cropped BGR


def _yolo():
    """Pose model, reused from the extraction pipeline so there is one download."""
    from ultralytics import YOLO  # type: ignore

    weights = Path(__file__).resolve().parent.parent / "pipeline" / "yolo11n-pose.pt"
    return YOLO(str(weights) if weights.exists() else "yolo11n-pose.pt")


# Below this, what was found is not a presenter. Measured on a narrated
# animation with no person in it at all, where the best "detection" scored
# 0.054 and was a piece of industrial equipment; a speaker who fills a
# reasonable part of the frame scores several times higher. Returning that crop
# anyway would hand back a confident-looking still of the wrong thing, which is
# worse than saying nothing was found.
MIN_SCORE = 0.15


def find_lecturer(
    video_path: Path,
    samples: int = 12,
    pad: float = 0.12,
    min_score: float = MIN_SCORE,
) -> LecturerShot | None:
    """Best still of the largest, most confident person across the video.

    Returns None when no frame holds a convincing person — a lecture recording
    may be slides, screen capture or animation with only a voice-over.

    Sampling rather than scanning every frame: a lecture is minutes long and the
    person barely moves, so a dozen frames spread across it find them as well as
    thousands would, in a fraction of the time.
    """
    cap = cv2.VideoCapture(str(video_path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    if total <= 0:
        cap.release()
        return None

    model = _yolo()
    best: LecturerShot | None = None

    # Skip the very start and end, which are title and summary cards more often
    # than they are the speaker.
    for i in range(samples):
        idx = int(total * (0.10 + 0.80 * (i / max(samples - 1, 1))))
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            continue

        result = model(frame, verbose=False)[0]
        if result.boxes is None or len(result.boxes) == 0:
            continue

        xyxy = result.boxes.xyxy.cpu().numpy()
        conf = result.boxes.conf.cpu().numpy()
        # Score by confidence AND area: a confident detection of someone in the
        # background is not the lecturer.
        h, w = frame.shape[:2]
        areas = (xyxy[:, 2] - xyxy[:, 0]) * (xyxy[:, 3] - xyxy[:, 1]) / float(w * h)
        score = conf * np.sqrt(np.clip(areas, 0, 1))
        j = int(np.argmax(score))
        if best is not None and float(score[j]) <= best.confidence:
            continue

        x1, y1, x2, y2 = xyxy[j]
        px, py = (x2 - x1) * pad, (y2 - y1) * pad
        x1 = int(max(x1 - px, 0))
        y1 = int(max(y1 - py, 0))
        x2 = int(min(x2 + px, w))
        y2 = int(min(y2 + py, h))
        if x2 - x1 < 40 or y2 - y1 < 40:
            continue

        best = LecturerShot(
            frame_index=idx,
            timestamp=idx / fps,
            confidence=float(score[j]),
            box=(x1, y1, x2 - x1, y2 - y1),
            image=frame[y1:y2, x1:x2].copy(),
        )

    cap.release()
    return best if best is not None and best.confidence >= min_score else None
