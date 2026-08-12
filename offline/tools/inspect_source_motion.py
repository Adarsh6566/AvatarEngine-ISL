"""CLI: inspect + visualize a HumanMotionSequence (SOURCE motion only).

    python offline/tools/inspect_source_motion.py --clip MVI_0029 --save out.png

Prints frame/timestamp/landmark/confidence/coordinate stats and, with --save,
draws body + both hands across several frames so you can see the signer move.
This is NOT an avatar visualization — it validates the captured source only.
"""
from __future__ import annotations

import argparse
import glob
import json
import statistics as st
import sys
from pathlib import Path

OFF = Path(__file__).resolve().parents[1]
SM = OFF / "output" / "source_motion"


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip")
    ap.add_argument("--save")
    a = ap.parse_args(argv[1:])

    hits = [p for p in glob.glob(str(SM / "*.json"))
            if not a.clip or a.clip.lower() in Path(p).name.lower()]
    if not hits:
        print("No source_motion file. Run capture_source_motion.py first.")
        return 1

    d = json.load(open(hits[0]))
    m, F = d["meta"], d["frames"]
    print(f"schema={m['schema']}  video={m['source_video']}  gloss={m['gloss']}")
    print(f"frames={m['frame_count']}  fps={m['fps']}  dur={m['duration']:.2f}s  "
          f"space={m['coordinate_space']}  estimator={m['estimator']}")
    print(f"landmarks/frame={m['landmark_groups']}  total={sum(m['landmark_groups'].values())}")

    bconf = [l["confidence"] for f in F for l in f["body"]]
    xs = [l["x"] for f in F for l in f["body"]]
    ys = [l["y"] for f in F for l in f["body"]]
    zs = [l["z"] for f in F for l in f["body"]]
    print(f"body confidence: mean={st.mean(bconf):.2f} min={min(bconf):.2f}")
    print(f"coord ranges  : x[{min(xs):.2f},{max(xs):.2f}] "
          f"y[{min(ys):.2f},{max(ys):.2f}] z[{min(zs):.2f},{max(zs):.2f}]")
    lh = sum(1 for f in F if f["left_hand"])
    rh = sum(1 for f in F if f["right_hand"])
    print(f"frames with left_hand={lh}/{len(F)}  right_hand={rh}/{len(F)}  "
          f"t0={F[0]['timestamp']:.2f}  tN={F[-1]['timestamp']:.2f}")

    if a.save:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        K = min(6, len(F))
        idx = [int(i * (len(F) - 1) / (K - 1)) for i in range(K)]
        fig, axes = plt.subplots(1, K, figsize=(3 * K, 3.6))
        for ax, i in zip(axes, idx):
            f = F[i]
            for pts, c, s in ((f["body"], "tab:blue", 7),
                              (f["left_hand"], "tab:green", 9),
                              (f["right_hand"], "tab:red", 9)):
                if pts:
                    ax.scatter([p["x"] for p in pts], [-p["y"] for p in pts], s=s, c=c)
            ax.set_title(f"f{i}  t={f['timestamp']:.2f}s", fontsize=8)
            ax.set_xlim(0, 1); ax.set_ylim(-1, 0)
            ax.set_xticks([]); ax.set_yticks([])
        fig.suptitle(f"{m['gloss']} SOURCE motion — body(blue) L-hand(green) R-hand(red)",
                     fontsize=11)
        fig.savefig(a.save, dpi=100)
        print("saved", a.save)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
