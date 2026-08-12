"""Step 2E: temporal missing-data repair of target_rotations.v1 (right-hand gap).

Holds/SLERPs derived rotations across frames where the SOURCE was missing, instead
of snapping to rest. Does NOT touch the solver, source, or any locked file.
Writes target_rotations_temporal.v1.json (original kept).

    python offline/tools/repair_temporal.py --save out.png
"""
from __future__ import annotations
import argparse, json, math, sys
from pathlib import Path
import numpy as np

OFF = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(OFF))
from motionpipe.target_rotations import _DC, build, extract_rest, qmul, qconj, qrot, IDENT  # noqa: E402

TMOT = OFF / "output" / "target_motion"
RAW = TMOT / "target_rotations.v1.json"
LARGE = 150.0  # deg: above this, a valid->valid gap is treated as suspicious -> HOLD


def ang(a, b):
    return 2 * math.degrees(math.acos(min(1.0, abs(float(np.dot(a, b))))))


def slerp(a, b, t):
    d = float(np.dot(a, b))
    if d < 0: b = -b; d = -d
    if d > 0.9995: return a + t * (b - a)
    th = math.acos(d); s = math.sin(th)
    return (math.sin((1 - t) * th) / s) * a + (math.sin(t * th) / s) * b


def scan(frames):
    stats = {}
    for b in frames[0]["rotations"]:
        chg = [ang(np.array(frames[i - 1]["rotations"][b]), np.array(frames[i]["rotations"][b]))
               for i in range(1, len(frames))]
        mx = max(chg); stats[b] = (float(np.mean(chg)), float(mx), int(np.argmax(chg)) + 1)
    return stats


def main(argv):
    ap = argparse.ArgumentParser(); ap.add_argument("--save"); a = ap.parse_args(argv[1:])
    raw = json.load(open(RAW)); tm = json.load(open(TMOT / "target_motion.v1.json"))
    F = raw["frames"]; n = len(F); bones = list(F[0]["rotations"])
    tmj = [f["joints"] for f in tm["frames"]]

    def observed(b, f):
        c = _DC.get(b)
        if b not in tmj[f] or c is None: return None  # constant/leaf: no repair
        ok = tmj[f][b]["validity"] and (c in tmj[f]) and tmj[f][c]["validity"]
        return ok

    # find missing frames per bone
    missing = {b: [f for f in range(n) if observed(b, f) is False] for b in bones}
    affected = {b: m for b, m in missing.items() if m}
    gap_frames = sorted({f for m in affected.values() for f in m})
    before = scan(F)

    # repair: per bone, fill unobserved runs
    Fc = [{"index": f["index"], "timestamp": f["timestamp"],
           "rotations": dict(f["rotations"]), "repair": {}} for f in F]
    for b, miss in affected.items():
        miss = sorted(miss); i = 0
        Q = {f: np.array(F[f]["rotations"][b]) for f in range(n)}
        while i < len(miss):
            j = i
            while j + 1 < len(miss) and miss[j + 1] == miss[j] + 1: j += 1
            g0, g1 = miss[i], miss[j]
            prev = g0 - 1 if g0 - 1 >= 0 and observed(b, g0 - 1) else None
            nxt = g1 + 1 if g1 + 1 < n and observed(b, g1 + 1) else None
            if prev is not None and nxt is not None:
                gap_ang = ang(Q[prev], Q[nxt])
                if gap_ang <= LARGE:
                    for k in range(g0, g1 + 1):
                        t = (k - prev) / (nxt - prev)
                        q = slerp(Q[prev], Q[nxt], t); q = q / np.linalg.norm(q)
                        Fc[k]["rotations"][b] = [round(float(c), 6) for c in q]
                        Fc[k]["repair"][b] = "interpolated"
                else:
                    for k in range(g0, g1 + 1):
                        Fc[k]["rotations"][b] = [round(float(c), 6) for c in Q[prev]]
                        Fc[k]["repair"][b] = "held_large_diff"
            else:
                src = prev if prev is not None else nxt
                for k in range(g0, g1 + 1):
                    Fc[k]["rotations"][b] = ([round(float(c), 6) for c in Q[src]] if src is not None
                                             else F[k]["rotations"][b])
                    Fc[k]["repair"][b] = "held" if src is not None else "original_missing"
            i = j + 1

    after = scan(Fc)
    out = {"meta": {**raw["meta"], "schema": "target_rotations_temporal.v1",
                    "derived_from": "target_rotations.v1.json",
                    "repair_policy": f"per-bone missing runs: SLERP if valid<->valid & gap<= {LARGE}deg,"
                    " else HOLD last valid; source unchanged; leaves/body/left untouched",
                    "gap_frames": gap_frames}, "frames": Fc}
    json.dump(out, open(TMOT / "target_rotations_temporal.v1.json", "w"))

    # ---- report ----
    print(f"gap frames (right-hand missing): {gap_frames}")
    print(f"affected bones ({len(affected)}): {sorted(affected)}")
    worst_b = max(before, key=lambda b: before[b][1])
    print(f"BEFORE worst jump: {worst_b} {before[worst_b][1]:.1f}deg @f{before[worst_b][2]}")
    worst_a = max(after, key=lambda b: after[b][1])
    print(f"AFTER  worst jump: {worst_a} {after[worst_a][1]:.1f}deg @f{after[worst_a][2]}")
    # right-hand specific
    rh = [b for b in affected]
    print(f"right-hand max jump BEFORE={max(before[b][1] for b in rh):.1f}  AFTER={max(after[b][1] for b in rh):.1f}")
    # validation: norms/nan, left/body unchanged, timestamps
    allq = np.array([q for f in Fc for q in f["rotations"].values()])
    print(f"norms[min={np.linalg.norm(allq,axis=1).min():.4f} max={np.linalg.norm(allq,axis=1).max():.4f}]  "
          f"NaN/Inf={int(np.sum(~np.isfinite(allq)))}  frames={len(Fc)} fps={out['meta']['fps']}")
    left_changed = any(Fc[f]["rotations"][b] != F[f]["rotations"][b]
                       for f in range(n) for b in bones if b.startswith("left") or b in ("hips", "spine", "chest"))
    print(f"left/body/legs modified? {left_changed}  timestamps_unchanged="
          f"{[f['timestamp'] for f in Fc]==[f['timestamp'] for f in F]}")
    print(f"-> {TMOT}/target_rotations_temporal.v1.json")

    if a.save:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(11, 4))
        for b, col in (("rightHand", "tab:red"), ("rightIndexProximal", "tab:orange")):
            rawc = [ang(np.array(F[i - 1]["rotations"][b]), np.array(F[i]["rotations"][b])) for i in range(1, n)]
            corc = [ang(np.array(Fc[i - 1]["rotations"][b]), np.array(Fc[i]["rotations"][b])) for i in range(1, n)]
            ax.plot(range(1, n), rawc, col, ls="--", alpha=.6, label=f"{b} raw")
            ax.plot(range(1, n), corc, col, lw=2, label=f"{b} repaired")
        for g in gap_frames: ax.axvspan(g - .5, g + .5, color="gray", alpha=.2)
        ax.set_xlabel("frame"); ax.set_ylabel("frame-to-frame rotation (deg)")
        ax.set_title("Step 2E — right-hand angular change: raw (dashed) vs repaired (solid), gap shaded")
        ax.legend(fontsize=8)
        fig.savefig(a.save, dpi=100, bbox_inches="tight"); print("saved", a.save)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
