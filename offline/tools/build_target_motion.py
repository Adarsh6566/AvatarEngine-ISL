"""CLI: build TargetMotionSequence v1 (target joint positions) + validate + visualize.

    python offline/tools/build_target_motion.py --clip MVI_0029 --save out.png

Consumes source_skeleton/ + target_skeleton/. Writes offline/output/target_motion/.
No rotations / IK / VRMA / runtime changes.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import sys
from pathlib import Path

import numpy as np

OFF = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OFF))
from motionpipe.target_motion import build_target_motion  # noqa: E402
from motionpipe.source_skeleton import HIERARCHY as SRC_HIER  # noqa: E402

SS, TS = OFF / "output" / "source_skeleton", OFF / "output" / "target_skeleton"
OUT = OFF / "output" / "target_motion"
_FING = [("Thumb", "Thumb"), ("Index", "Index"), ("Middle", "Middle"), ("Ring", "Ring"), ("Little", "Pinky")]


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip"); ap.add_argument("--save")
    a = ap.parse_args(argv[1:])
    sp = next((p for p in glob.glob(str(SS / "*.json"))
               if not a.clip or a.clip.lower() in Path(p).name.lower()), None)
    if not sp:
        print("No source_skeleton. Run build_source_skeleton.py first."); return 1
    src = json.load(open(sp))
    tgt = json.load(open(TS / "target_skeleton.json"))
    mapping = json.load(open(TS / "skeleton_mapping.json"))
    calib = json.load(open(TS / "calibration.json"))
    tm = build_target_motion(src, tgt, mapping, calib)
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(tm, open(OUT / "target_motion.v1.json", "w"))

    F = tm["frames"]; m = tm["meta"]
    # numerical + temporal validation
    allpos = [j["position"] for f in F for j in f["joints"].values() if j["position"]]
    arr = np.array(allpos)
    nan = int(np.sum(~np.isfinite(arr)))
    absurd = int(np.sum(np.abs(arr) > 10))
    # per-frame motion magnitude (mean joint displacement between frames), for VRM bones
    bones = [t for t, j in F[0]["joints"].items() if j["vrm_bone"]]
    mags = []
    for i in range(1, len(F)):
        ds = []
        for b in bones:
            p, q = F[i]["joints"][b]["position"], F[i - 1]["joints"][b]["position"]
            if p and q:
                ds.append(math.dist(p, q))
        mags.append(sum(ds) / len(ds) if ds else 0.0)
    lh = sum(1 for f in F if f["joints"].get("leftHand", {}).get("validity"))
    rh = sum(1 for f in F if f["joints"].get("rightHand", {}).get("validity"))
    lf = sum(1 for f in F if all(f["joints"][f"left{fj}Distal"]["validity"] for fj, _ in _FING))
    rf = sum(1 for f in F if all(f["joints"][f"right{fj}Distal"]["validity"] for fj, _ in _FING))
    ts_ok = [f["timestamp"] for f in F] == [f["timestamp"] for f in src["frames"]]

    print(f"schema={m['schema']}  represents={m['represents']}")
    print(f"frames={m['frame_count']} fps={m['fps']} dur={m['duration']:.2f}s  timestamps_unchanged={ts_ok}")
    print(f"det(R)={m['transform']['det_R']} (≈1 => proper rotation)  construction={m.get('construction','')[:60]}")
    print(f"coord range x[{arr[:,0].min():.2f},{arr[:,0].max():.2f}] "
          f"y[{arr[:,1].min():.2f},{arr[:,1].max():.2f}] z[{arr[:,2].min():.2f},{arr[:,2].max():.2f}] (meters)")
    print(f"NaN/Inf={nan}  |coord|>10m={absurd}")
    print(f"per-frame motion mag: mean={np.mean(mags):.4f} max={np.max(mags):.4f} min={np.min(mags):.4f} m")
    print(f"hand valid: left={lh}/{len(F)} right={rh}/{len(F)}")
    print(f"all-5-fingers Distal valid: left={lf}/{len(F)} right={rf}/{len(F)}")
    print(f"-> {OUT}/target_motion.v1.json")

    if a.save:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        # target edges: body/finger hierarchy among mapped bones + distal->tip
        thier = [(p, c) for p, c in tgt["hierarchy"]
                 if p in F[0]["joints"] and c in F[0]["joints"]]
        for s in ("left", "right"):
            for vf, sf in _FING:
                thier.append((f"{s}{vf}Distal", f"{s}{sf}TIP"))
        K = 6; idx = [int(i * (len(F) - 1) / (K - 1)) for i in range(K)]
        fig, axes = plt.subplots(2, K, figsize=(3 * K, 7))
        for col, i in enumerate(idx):
            # source (top)
            Js = src["frames"][i]["joints"]; axs = axes[0][col]
            for p, c in SRC_HIER:
                pa, pb = Js.get(p), Js.get(c)
                if pa and pb:
                    axs.plot([pa[0], pb[0]], [-pa[1], -pb[1]], c="dimgray", lw=0.8)
            axs.set_title(f"src f{i}", fontsize=8); axs.set_xlim(0.2, 0.8); axs.set_ylim(-1.4, 0)
            # target (bottom), VRM space x,y
            Jt = F[i]["joints"]; axt = axes[1][col]
            for p, c in thier:
                pa, pb = Jt.get(p, {}).get("position"), Jt.get(c, {}).get("position")
                if pa and pb:
                    col2 = "tab:green" if "left" in c and any(k in c for k in ("Thumb","Index","Middle","Ring","Little","Hand","TIP")) \
                        else "tab:red" if "right" in c and any(k in c for k in ("Thumb","Index","Middle","Ring","Little","Hand","TIP")) else "black"
                    axt.plot([pa[0], pb[0]], [pa[1], pb[1]], c=col2, lw=0.9)
            axt.set_title(f"tgt f{i} t={F[i]['timestamp']:.2f}s", fontsize=8)
            for ax in (axs, axt):
                ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
        fig.suptitle("Step 2C — SOURCE (top, img space) vs TARGET MOTION (bottom, VRM space). L-hand green R-hand red", fontsize=10)
        fig.savefig(a.save, dpi=100); print("saved", a.save)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
