"""Stage 0 — Ingest.

Responsibility: discover source videos and turn each into one ClipMeta.
Input : a datasets root directory (defaults to offline/datasets/)
Output: list[ClipMeta]
Owner : this module.

- Recursively scans the root for video files (any common extension, so a dataset
  of .MOV or .mp4 both work).
- Infers the sign label from the immediate parent folder (uppercased).
- Reads capture metadata (fps / frame_count / duration / resolution) via `ffprobe`
  when it is on PATH; otherwise those fields stay None. No OpenCV / MediaPipe /
  pose work happens here.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .models import ClipMeta

# Directory this stage scans by default: offline/datasets/
DATASETS_DIR = Path(__file__).resolve().parents[1] / "datasets"

# Video containers we recognise (compared case-insensitively).
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}


def ingest(root: str | Path = DATASETS_DIR) -> list[ClipMeta]:
    """Scan `root` recursively and return one ClipMeta per video, sorted by
    (gloss, filename). Raises FileNotFoundError if `root` does not exist."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"datasets root not found: {root}")

    clips: list[ClipMeta] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        clips.append(_to_clip(path, root))

    clips.sort(key=lambda c: (c.gloss, c.filename))
    return clips


def _to_clip(path: Path, root: Path) -> ClipMeta:
    """Build a ClipMeta for one video file."""
    rel = path.relative_to(root)
    fps, frame_count, duration, resolution = _probe(path)
    return ClipMeta(
        gloss=path.parent.name.upper(),          # label from parent dir
        clip_id=rel.with_suffix("").as_posix(),  # e.g. "isl_greeting/hello/MVI_0037"
        filename=path.name,
        source_path=str(path),
        dataset=rel.parts[0] if len(rel.parts) > 1 else path.parent.name,
        fps=fps,
        frame_count=frame_count,
        duration=duration,
        resolution=resolution,
    )


def _probe(path: Path):
    """Best-effort capture metadata via ffprobe.

    Returns (fps, frame_count, duration, resolution), any of which may be None.
    Never raises: if ffprobe is missing or the file is unreadable, all None.
    """
    if shutil.which("ffprobe") is None:
        return None, None, None, None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
        data = json.loads(out)
    except (subprocess.SubprocessError, OSError, ValueError):
        return None, None, None, None

    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    duration = _as_float(data.get("format", {}).get("duration"))
    resolution = None
    if "width" in video and "height" in video:
        resolution = (int(video["width"]), int(video["height"]))
    return (
        _as_fps(video.get("avg_frame_rate")),
        _as_int(video.get("nb_frames")),
        duration,
        resolution,
    )


def _as_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _as_fps(v):
    """Parse ffprobe's "num/den" frame-rate string into fps."""
    try:
        num, den = str(v).split("/")
        return float(num) / float(den) if float(den) else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None
