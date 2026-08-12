"""CLI: HumanMotionSequence JSON -> SourceSkeletonSequence JSON (positions only).

    python offline/tools/build_source_skeleton.py --clip MVI_0029

Reads offline/output/source_motion/, writes offline/output/source_skeleton/.
No rotations, no VRM, no resample/smooth/trim. Old pipeline untouched.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

OFF = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OFF))

from motionpipe.source_skeleton import from_human_motion  # noqa: E402

SRC = OFF / "output" / "source_motion"
OUT = OFF / "output" / "source_skeleton"


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip")
    ap.add_argument("--input")
    a = ap.parse_args(argv[1:])

    path = a.input or next(
        (p for p in glob.glob(str(SRC / "*.json"))
         if not a.clip or a.clip.lower() in Path(p).name.lower()), None)
    if not path:
        print("No source_motion file. Run capture_source_motion.py first.")
        return 1

    hm = json.load(open(path))
    ss = from_human_motion(hm)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / Path(path).name
    with out.open("w", encoding="utf-8") as f:
        json.dump(ss, f)

    m = ss["meta"]
    print(f"schema={m['schema']}  gloss={m['gloss']}  video={m['source_video']}")
    print(f"frames={m['frame_count']}  fps={m['fps']}  joints={m['joint_count']}  "
          f"space={m['coordinate_space']}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
