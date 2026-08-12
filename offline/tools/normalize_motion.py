"""CLI: SkeletalMotion JSON -> NormalizedMotion JSON.

    python offline/tools/normalize_motion.py --clip MVI_0029 --fps 24 --smooth 3

Reads output/motions/, writes output/normalized/. No retargeting/export.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

OFFLINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OFFLINE))

from motionpipe import io  # noqa: E402
from motionpipe.config import PipelineConfig  # noqa: E402
from motionpipe.models import ClipMeta, SkeletalBone, SkeletalFrame, SkeletalMotion  # noqa: E402
from motionpipe.normalize import normalize  # noqa: E402

MOTIONS_DIR = OFFLINE / "output" / "motions"
OUT_DIR = OFFLINE / "output" / "normalized"


def _tup(v):
    return None if v is None else tuple(v)


def rehydrate(d) -> SkeletalMotion:
    frames = [
        SkeletalFrame(f["t"], [SkeletalBone(b["name"], b["parent"], tuple(b["local_position"]),
                                            _tup(b["local_rotation"]), b["confidence"])
                               for b in f["bones"]])
        for f in d["frames"]
    ]
    return SkeletalMotion(d["skeleton"], d["fps"], frames, d["confidence"], ClipMeta(**d["meta"]))


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="Normalize canonical skeletal motion.")
    ap.add_argument("--clip", help="match a file in output/motions/ by substring")
    ap.add_argument("--input")
    ap.add_argument("--fps", type=float, default=24.0)
    ap.add_argument("--smooth", type=int, default=1, help="odd frame window; 1=off")
    ap.add_argument("--no-trim", action="store_true")
    args = ap.parse_args(argv[1:])

    path = args.input or next(
        (p for p in glob.glob(str(MOTIONS_DIR / "*.json"))
         if not args.clip or args.clip.lower() in Path(p).name.lower()), None)
    if not path:
        print("No motion file matched. Run reconstruct_motion.py first.")
        return 1

    motion = rehydrate(json.load(open(path)))
    cfg = PipelineConfig(target_fps=args.fps, smoothing_window=args.smooth, trim=not args.no_trim)
    norm = normalize(motion, cfg)
    out = OUT_DIR / Path(path).name
    io.write(norm, out)

    print(f"original fps    : {motion.fps:.1f}")
    print(f"normalized fps  : {norm.fps:.1f}")
    print(f"original frames : {len(motion.frames)}")
    print(f"normalized frame: {len(norm.frames)}")
    print(f"scale factor    : {norm.scale_factor:.3f}  (unit-torso)")
    print(f"trimmed frames  : {norm.trimmed_frames}")
    print(f"duration        : {norm.duration:.2f}s")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
