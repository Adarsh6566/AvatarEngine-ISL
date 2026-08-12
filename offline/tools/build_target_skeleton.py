"""CLI: build target_skeleton.v1 + skeleton_mapping.v1 + calibration.v1 and validate
against the real HELLO source_skeleton. Geometry + correspondence only.

    python offline/tools/build_target_skeleton.py --clip MVI_0029 --save out.png

Writes to offline/output/target_skeleton/. No rotations / IK / VRMA / runtime.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import statistics as st
import sys
from pathlib import Path

OFF = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OFF))
from motionpipe.target_skeleton import (SOURCE_COORD, TARGET_COORD, extract_target,  # noqa: E402
                                        source_to_target)
from motionpipe.source_skeleton import HIERARCHY as SRC_HIER  # noqa: E402

SS = OFF / "output" / "source_skeleton"
OUT = OFF / "output" / "target_skeleton"


def _seg_len(J, a, b):
    pa, pb = J.get(a), J.get(b)
    return math.dist(pa[:3], pb[:3]) if pa and pb else None


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip"); ap.add_argument("--save")
    a = ap.parse_args(argv[1:])
    hit = next((p for p in glob.glob(str(SS / "*.json"))
                if not a.clip or a.clip.lower() in Path(p).name.lower()), None)
    if not hit:
        print("No source_skeleton file. Run build_source_skeleton.py first.")
        return 1
    src = json.load(open(hit)); F = src["frames"]
    target = extract_target()
    tgt_names = {b["name"] for b in target["bones"]}
    tgt_len = {b["name"]: b["bone_length_from_parent"] for b in target["bones"]}
    tgt_parent = {b["name"]: b["parent"] for b in target["bones"]}
    src_names = {j for f in F for j in f["joints"]}
    m = source_to_target()

    mapped = {t: s for t, s in m.items() if s is not None}
    unmapped_target = sorted(t for t in tgt_names if m.get(t) is None)
    used_src = set(mapped.values())
    unmapped_source = sorted(s for s in src_names if s not in used_src)

    # per-bone morphology calibration: source observed length vs target rest length
    per_bone = []
    for tb, sj in mapped.items():
        tp = tgt_parent.get(tb); sp = m.get(tp) if tp else None
        slens = [_seg_len(f["joints"], sp, sj) for f in F] if sp else []
        slens = [x for x in slens if x is not None]
        slen = round(st.median(slens), 4) if slens else None
        tl = tgt_len.get(tb)
        ratio = round(tl / slen, 3) if (tl and slen) else None
        per_bone.append({"target": tb, "source": sj, "source_len_median": slen,
                         "target_len": tl, "ratio": ratio})
    ratios = [p["ratio"] for p in per_bone if p["ratio"]]
    calibration = {
        "schema": "calibration.v1",
        "coordinate_contract": {
            "source": SOURCE_COORD, "target": TARGET_COORD,
            "operation": "SourceToTargetCalibration",
            "established": {"y_up_flip": "180deg about X (y->-y, z->-z); handedness preserved",
                            "scale": "normalized->meters via bone-length ratio (global_scale below)"},
            "deferred": {"facing_sign": "exact front-facing rotation NOT derivable from geometry "
                         "alone; resolve in 2C via a reference direction"},
            "applied": False},
        "reference_pose": {
            "source_reference": "PROXY = per-bone MEDIAN observed length over the clip; the video "
            "is a SIGN and contains NO reliable rest/T-pose",
            "source_reference_is_fabricated": False,
            "target_rest": "VRM rest pose (from asset)"},
        "global_scale_estimate": round(st.median(ratios), 3) if ratios else None,
        "per_bone": per_bone}
    mapping = {"schema": "skeleton_mapping.v1", "target_asset": target["source_asset"],
               "map": m, "mapped_count": len(mapped),
               "unmapped_target": unmapped_target, "unmapped_source": unmapped_source}

    OUT.mkdir(parents=True, exist_ok=True)
    for name, obj in (("target_skeleton", target), ("skeleton_mapping", mapping),
                      ("calibration", calibration)):
        json.dump(obj, open(OUT / f"{name}.json", "w"))

    # --- validation report ---
    bad_src = [t for t, s in mapped.items() if s not in src_names]
    bad_tgt = [t for t in mapped if t not in tgt_names]
    nan = any(not math.isfinite(c) for b in target["bones"] for c in b["rest_world"])
    fingers = lambda side: [t for t in mapped if t.startswith(side) and any(
        f in t for f in ("Thumb", "Index", "Middle", "Ring", "Little"))]
    print(f"target: {target['source_asset']}  bones={target['bone_count']}  space=VRM1 Y-up metric")
    print(f"mapped: {len(mapped)} source joints -> target bones")
    print(f"unmapped target ({len(unmapped_target)}): {unmapped_target}")
    print(f"unmapped source ({len(unmapped_source)}): {unmapped_source}")
    print(f"finger bones mapped: left={len(fingers('left'))} right={len(fingers('right'))} (15 each expected)")
    print(f"mapped source joints missing from source? {bad_src or 'none'}")
    print(f"mapped target bones missing from target? {bad_tgt or 'none'}")
    print(f"target rest NaN/Inf? {nan}   global scale (target/source) ~ {calibration['global_scale_estimate']}")
    print(f"source frames={len(F)} fps={src['meta']['fps']} t0={F[0]['timestamp']:.2f} tN={F[-1]['timestamp']:.2f}")
    print(f"-> {OUT}/ (target_skeleton, skeleton_mapping, calibration).json")

    if a.save:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, (axS, axT) = plt.subplots(1, 2, figsize=(11, 5.5))
        J = F[5]["joints"]
        for p, c in SRC_HIER:
            pa, pb = J.get(p), J.get(c)
            if pa and pb:
                col = "tab:green" if "left" in c.lower() and any(k in c for k in ("Thumb","Index","Middle","Ring","Pinky","Hand")) \
                    else "tab:red" if "right" in c.lower() and any(k in c for k in ("Thumb","Index","Middle","Ring","Pinky","Hand")) else "black"
                axS.plot([pa[0], pb[0]], [-pa[1], -pb[1]], c=col, lw=1)
        axS.set_title("SOURCE skeleton (frame 5, MediaPipe img space)", fontsize=9)
        axS.set_xlim(0.2, 0.8); axS.set_ylim(-1.4, 0); axS.set_aspect("equal")
        pos = {b["name"]: b["rest_world"] for b in target["bones"]}
        for p, c in target["hierarchy"]:
            pa, pb = pos[p], pos[c]
            col = "tab:green" if c.startswith("left") and any(k in c for k in ("Thumb","Index","Middle","Ring","Little","Hand")) \
                else "tab:red" if c.startswith("right") and any(k in c for k in ("Thumb","Index","Middle","Ring","Little","Hand")) else "black"
            axT.plot([pa[0], pb[0]], [pa[1], pb[1]], c=col, lw=1)
        axT.set_title("TARGET skeleton (VRM rest, Y-up meters)", fontsize=9)
        axT.set_aspect("equal")
        for ax in (axS, axT):
            ax.set_xticks([]); ax.set_yticks([])
        fig.suptitle("Step 2B — SOURCE vs TARGET (own coord spaces). body=black L-hand=green R-hand=red", fontsize=10)
        fig.savefig(a.save, dpi=100); print("saved", a.save)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
