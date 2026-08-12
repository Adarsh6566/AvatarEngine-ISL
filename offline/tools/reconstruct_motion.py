"""CLI: PoseSequence JSON -> SkeletalMotion JSON.

    python offline/tools/reconstruct_motion.py --clip MVI_0029
    python offline/tools/reconstruct_motion.py --input offline/output/poses/<file>.json

Reads from output/poses/, writes to output/motions/. No retargeting/normalization.
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
from motionpipe.models import ClipMeta, Landmark, PoseFrame, PoseSequence  # noqa: E402
from motionpipe.reconstruct import BONES, reconstruct  # noqa: E402

POSES_DIR = OFFLINE / "output" / "poses"
MOTIONS_DIR = OFFLINE / "output" / "motions"


def rehydrate(d) -> PoseSequence:
    frames = [
        PoseFrame(t=f["t"], landmarks={k: Landmark(**v) for k, v in f["landmarks"].items()})
        for f in d["frames"]
    ]
    return PoseSequence(d["landmark_set"], d["estimator"], d["fps"], d["space"],
                        frames, ClipMeta(**d["meta"]))


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="Reconstruct canonical skeletal motion.")
    ap.add_argument("--input", help="path to a PoseSequence JSON")
    ap.add_argument("--clip", help="match a file in output/poses/ by substring")
    args = ap.parse_args(argv[1:])

    if args.input:
        path = args.input
    else:
        hits = [p for p in glob.glob(str(POSES_DIR / "*.json"))
                if not args.clip or args.clip.lower() in Path(p).name.lower()]
        if not hits:
            print("No pose file matched. Run extract_pose.py first.")
            return 1
        path = hits[0]

    seq = rehydrate(json.load(open(path)))
    motion = reconstruct(seq)
    out = MOTIONS_DIR / Path(path).name
    io.write(motion, out)

    n = len(motion.frames)
    b0 = motion.frames[0].bones if n else []
    no_rot = sum(1 for f in motion.frames for b in f.bones if b.local_rotation is None)
    total = sum(len(f.bones) for f in motion.frames) or 1
    print(f"skeleton     : {motion.skeleton}  ({len(BONES)} bones)")
    print(f"frames       : {n}  fps={motion.fps:.1f}")
    print(f"mean conf    : {motion.confidence:.3f}")
    print(f"null rotation: {no_rot}/{total} bone-frames ({100*no_rot/total:.0f}%)")
    print(f"root (hips)  : pos={_r(b0[0].local_position)} rot={_r(b0[0].local_rotation)}")
    if len(b0) > 4:
        print(f"leftLowerArm : rot={_r(b0[4].local_rotation)} conf={b0[4].confidence:.2f}")
    print(f"-> {out}")
    return 0


def _r(v):
    if v is None:
        return None
    return tuple(round(c, 3) for c in v)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
