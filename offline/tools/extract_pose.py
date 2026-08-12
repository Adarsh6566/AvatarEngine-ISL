"""CLI: run pose extraction on selected clips, saving one PoseSequence each.

    python offline/tools/extract_pose.py --label HELLO
    python offline/tools/extract_pose.py --clip MVI_0037
    python offline/tools/extract_pose.py --label HELLO --max-frames 60 --stride 2

Output: offline/output/poses/<clip_id>.json (one file per video).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

OFFLINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OFFLINE))

from motionpipe import io  # noqa: E402
from motionpipe.ingest import ingest  # noqa: E402
from motionpipe.estimators import registry  # noqa: E402
import motionpipe.estimators.mediapipe  # noqa: E402,F401  (self-registers)

POSES_DIR = OFFLINE / "output" / "poses"


def select(clips, label, clip):
    if label:
        return [c for c in clips if c.gloss == label.upper()]
    if clip:
        key = clip.lower()
        return [c for c in clips if key in c.filename.lower() or key in c.clip_id.lower()]
    return clips


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="Extract MediaPipe Holistic poses.")
    ap.add_argument("--label", help="only clips with this sign label, e.g. HELLO")
    ap.add_argument("--clip", help="only clips whose filename/id contains this")
    ap.add_argument("--estimator", default="mediapipe_holistic")
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--stride", type=int, default=1, help="process every Nth frame")
    args = ap.parse_args(argv[1:])

    estimator = registry.get(args.estimator)
    clips = select(ingest(), args.label, args.clip)
    if not clips:
        print("No clips matched.")
        return 1

    print(f"Extracting poses from {len(clips)} clip(s) with {args.estimator}\n")
    for i, meta in enumerate(clips, 1):
        print(f"[{i}/{len(clips)}] {meta.gloss}/{meta.filename} …", flush=True)
        seq = estimator.estimate(
            meta.source_path, meta, max_frames=args.max_frames, stride=args.stride
        )
        out = POSES_DIR / (meta.clip_id.replace("/", "__") + ".json")
        io.write(seq, out)

        n = len(seq.frames)
        with_hands = sum(
            1 for f in seq.frames
            if any(k.startswith(("LEFT_HAND", "RIGHT_HAND")) for k in f.landmarks)
        )
        pts = len(seq.frames[0].landmarks) if n else 0
        print(f"    frames={n}  fps={seq.fps:.1f}  landmarks/frame={pts}  "
              f"frames_with_hands={with_hands}  -> {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
