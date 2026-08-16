"""Video helpers — probe, iterate, write skeleton mp4."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Generator, List, Tuple

import cv2
import numpy as np

from .schemas import CANONICAL_EDGES


def probe_video(path: Path) -> Tuple[float, int, int, int]:
    """Return (fps, width, height, frame_count). Falls back to 30 fps if probe fails."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return 30.0, 640, 480, 0
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or math.isnan(fps) or fps < 1:
        fps = 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    cap.release()
    return fps, w, h, n


def iter_frames(path: Path) -> Generator[Tuple[int, np.ndarray], None, None]:
    cap = cv2.VideoCapture(str(path))
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        yield idx, frame
        idx += 1
    cap.release()


def _project_to_canvas(
    joint: Tuple[float, float, float, float],
    canvas_w: int,
    canvas_h: int,
    scale: float = 180,
    is_3d: bool = False,
) -> Tuple[int, int]:
    """
    Project a view-space joint (already root-centered, unit scale) to canvas pixels.
    For 2D we do orthographic; for 3D we add a tiny perspective on z.
    """
    x, y, z, _ = joint
    # flip handled upstream; here y is Y-up → canvas Y-down invert
    # simple perspective: nearer (z) slightly larger
    perspective = 1.0 / (1.0 + max(0, z) * 0.5) if is_3d else 1.0
    cx = int(canvas_w / 2 + x * scale * perspective)
    cy = int(canvas_h / 2 - y * scale * perspective)  # Y-up → canvas down
    return cx, cy


def write_skeleton_video(
    frames_joints: List[dict],
    out_path: Path,
    fps: float,
    canvas_w: int = 640,
    canvas_h: int = 640,
    is_3d: bool = False,
    draw_original: bool = False,
    original_frames: List[np.ndarray] | None = None,
) -> None:
    """
    Write a skeleton-only mp4 from view-space joints. If draw_original and
    original_frames provided, overlays skeleton on top of dimmed original.
    """
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_path), fourcc, fps, (canvas_w, canvas_h))
    if not writer.isOpened():
        raise RuntimeError(f"VideoWriter failed to open {out_path}")

    for i, joints in enumerate(frames_joints):
        if draw_original and original_frames and i < len(original_frames):
            base = cv2.resize(original_frames[i], (canvas_w, canvas_h))
            canvas = cv2.addWeighted(base, 0.35, np.zeros_like(base), 0.65, 0)
            canvas = cv2.convertScaleAbs(canvas, alpha=1.1, beta=10)
        else:
            canvas = np.full((canvas_h, canvas_w, 3), 18, dtype=np.uint8)
            # faint grid
            for gx in range(0, canvas_w, 80):
                cv2.line(canvas, (gx, 0), (gx, canvas_h), (30, 30, 40), 1)
            for gy in range(0, canvas_h, 80):
                cv2.line(canvas, (0, gy), (canvas_w, gy), (30, 30, 40), 1)

        # draw edges
        for a, b in CANONICAL_EDGES:
            ja = joints.get(a)
            jb = joints.get(b)
            if ja is None or jb is None:
                continue
            try:
                pa = _project_to_canvas(ja, canvas_w, canvas_h, is_3d=is_3d)
                pb = _project_to_canvas(jb, canvas_w, canvas_h, is_3d=is_3d)
            except Exception:
                continue
            # halo
            cv2.line(canvas, pa, pb, (255, 160, 40), 4, cv2.LINE_AA)
            cv2.line(canvas, pa, pb, (120, 240, 255), 2, cv2.LINE_AA)

        # draw joints
        for name, v in joints.items():
            if v is None:
                continue
            p = _project_to_canvas(v, canvas_w, canvas_h, is_3d=is_3d)
            # head larger
            r = 6 if name == "head" else 4
            col = (255, 255, 255) if name not in ("lHand", "rHand") else (80, 255, 120)
            cv2.circle(canvas, p, r, col, -1, cv2.LINE_AA)
            cv2.circle(canvas, p, r + 2, (255, 255, 255), 1, cv2.LINE_AA)

        writer.write(canvas)

    writer.release()
