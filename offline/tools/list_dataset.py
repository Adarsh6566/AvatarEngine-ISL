"""CLI: list every discovered clip, grouped by sign label.

    python offline/tools/list_dataset.py [datasets_root]

Prints a count then each label with its filenames. Read-only — pure discovery,
no processing. Runs standalone; adds the offline/ dir to sys.path so `motionpipe`
imports without installation.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # offline/

from motionpipe.ingest import DATASETS_DIR, ingest  # noqa: E402


def main(argv: list[str]) -> int:
    root = argv[1] if len(argv) > 1 else DATASETS_DIR
    clips = ingest(root)

    print(f"Found {len(clips)} clips\n")

    # Group by label, preserving first-seen order.
    groups: dict[str, list[str]] = {}
    for clip in clips:
        groups.setdefault(clip.gloss, []).append(clip.filename)

    for label, filenames in groups.items():
        print(label)
        for name in filenames:
            print(f"    {name}")
        print()

    if clips and clips[0].fps is None:
        print("(capture metadata unavailable — install ffmpeg/ffprobe to populate "
              "fps, duration, resolution)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
