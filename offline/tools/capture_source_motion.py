"""CLI: real ISL video -> HumanMotionSequence (FULL temporal capture).

    python offline/tools/capture_source_motion.py --clip MVI_0029

Reuses the existing MediaPipe Holistic estimator at FULL resolution (stride 1, no
frame cap). Saves to offline/output/source_motion/. No bone reduction, no rotations.
Does not touch the old pipeline or its outputs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

OFF = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OFF))

from motionpipe.ingest import ingest  # noqa: E402
from motionpipe.estimators import registry  # noqa: E402
import motionpipe.estimators.mediapipe  # noqa: E402,F401  (self-registers)
from motionpipe.source_motion import from_pose_sequence, to_dict  # noqa: E402

OUT = OFF / "output" / "source_motion"


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="Capture full source motion from one video.")
    ap.add_argument("--clip")
    ap.add_argument("--label")
    ap.add_argument("--estimator", default="mediapipe_holistic")
    a = ap.parse_args(argv[1:])

    clips = ingest()
    if a.clip:
        clips = [c for c in clips if a.clip.lower() in c.filename.lower()
                 or a.clip.lower() in c.clip_id.lower()]
    elif a.label:
        clips = [c for c in clips if c.gloss == a.label.upper()]
    if not clips:
        print("No clip matched.")
        return 1

    meta = clips[0]
    est = registry.get(a.estimator)
    print(f"Capturing {meta.gloss}/{meta.filename} — full sequence, no stride/cap …", flush=True)
    ps = est.estimate(meta.source_path, meta)          # stride=1, max_frames=None
    seq = from_pose_sequence(ps, meta.gloss, meta.filename)

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / (meta.clip_id.replace("/", "__") + ".json")
    with out.open("w", encoding="utf-8") as f:
        json.dump(to_dict(seq), f)

    m = seq.meta
    print(f"frames={m.frame_count}  fps={m.fps}  duration={m.duration:.2f}s")
    print(f"landmarks/frame: {m.landmark_groups}  "
          f"total={sum(m.landmark_groups.values())}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
