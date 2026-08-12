"""CLI: inspect + visualize a SourceSkeletonSequence (SOURCE skeleton, not avatar).

    python offline/tools/inspect_source_skeleton.py --clip MVI_0029 --save out.png

Validates frame/fps/joint preservation, hand/finger validity, NaN/Inf, then draws
the body skeleton + both hands (finger chains) across several frames.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import sys
from pathlib import Path

OFF = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OFF))
from motionpipe.source_skeleton import HIERARCHY  # noqa: E402

SS = OFF / "output" / "source_skeleton"


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip")
    ap.add_argument("--save")
    a = ap.parse_args(argv[1:])
    hits = [p for p in glob.glob(str(SS / "*.json"))
            if not a.clip or a.clip.lower() in Path(p).name.lower()]
    if not hits:
        print("No source_skeleton file. Run build_source_skeleton.py first.")
        return 1

    d = json.load(open(hits[0]))
    m, F = d["meta"], d["frames"]
    names = [j["name"] for j in m["joints"]]
    print(f"schema={m['schema']}  gloss={m['gloss']}  video={m['source_video']}")
    print(f"frames={m['frame_count']}  fps={m['fps']}  joints={m['joint_count']}  space={m['coordinate_space']}")

    # validity + NaN scan
    lh = sum(1 for f in F if f["joints"].get("leftHandWrist"))
    rh = sum(1 for f in F if f["joints"].get("rightHandWrist"))
    nan = 0
    for f in F:
        for v in f["joints"].values():
            if v and any(not math.isfinite(c) for c in v):
                nan += 1
    body_ok = all(F[0]["joints"].get(n) for n in ["hips", "spine", "chest", "neck", "head"])
    lfing = ["leftThumbTIP", "leftIndexTIP", "leftMiddleTIP", "leftRingTIP", "leftPinkyTIP"]
    lfing_ok = sum(1 for f in F if all(f["joints"].get(n) for n in lfing))
    print(f"left hand valid = {lh}/{len(F)}   right hand valid = {rh}/{len(F)}")
    print(f"body core joints present frame0 = {body_ok}")
    print(f"frames with ALL 5 left-finger tips = {lfing_ok}/{len(F)}")
    print(f"NaN/Inf joint positions = {nan}")
    # parent/child integrity
    bad = [(p, c) for p, c in HIERARCHY if p not in names or c not in names]
    print(f"invalid hierarchy edges = {len(bad)}  (edges total {len(HIERARCHY)})")
    print(f"timestamps: t0={F[0]['timestamp']:.2f}  tN={F[-1]['timestamp']:.2f}  monotonic="
          f"{all(F[i]['timestamp'] <= F[i+1]['timestamp'] for i in range(len(F)-1))}")

    if a.save:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        K = min(6, len(F))
        idx = [int(i * (len(F) - 1) / (K - 1)) for i in range(K)]
        fig, axes = plt.subplots(1, K, figsize=(3 * K, 4))
        for ax, i in zip(axes, idx):
            J = F[i]["joints"]

            def seg(p, c, col, lw=1.5):
                a_, b_ = J.get(p), J.get(c)
                if a_ and b_:
                    ax.plot([a_[0], b_[0]], [-a_[1], -b_[1]], c=col, lw=lw)
            for p, c in HIERARCHY:
                col = "tab:green" if p.startswith("left") and "Hand" in p or c.startswith("left") and any(
                    k in c for k in ["Thumb", "Index", "Middle", "Ring", "Pinky"]) \
                    else "tab:red" if c.startswith("right") and any(
                    k in c for k in ["Thumb", "Index", "Middle", "Ring", "Pinky", "Hand"]) \
                    else "black"
                seg(p, c, col, 1.2 if col == "black" else 0.9)
            ax.set_title(f"f{i} t={F[i]['timestamp']:.2f}s", fontsize=8)
            ax.set_xlim(0.2, 0.8); ax.set_ylim(-1.4, 0)
            ax.set_xticks([]); ax.set_yticks([]); ax.set_aspect("equal")
        fig.suptitle(f"{m['gloss']} SOURCE SKELETON — body(black) L-hand(green) R-hand(red)", fontsize=11)
        fig.savefig(a.save, dpi=100)
        print("saved", a.save)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
