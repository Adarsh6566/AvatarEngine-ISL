"""Step 2F: re-derive rotations with the stabilized near-antiparallel swing, then
re-apply the 2E missing-data repair. Writes target_rotations_stable.v1.json.
Does not overwrite target_rotations.v1 / _temporal.v1.

    python offline/tools/stabilize_rotations.py --save out.png
"""
from __future__ import annotations
import argparse, json, math, sys
from pathlib import Path
import numpy as np

OFF = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OFF)); sys.path.insert(0, str(OFF / "tools"))
from motionpipe.target_rotations import (build, extract_rest, _DC, qmul, qconj, qrot, IDENT,  # noqa: E402
                                         ANTIPARALLEL_DOT)
from repair_temporal import ang, slerp, scan  # noqa: E402  (reuse 2E helpers)

TMOT = OFF / "output" / "target_motion"
LARGE = 150.0


def repair(frames, tm, order):
    n = len(frames); bones = list(frames[0]["rotations"]); tmj = [f["joints"] for f in tm["frames"]]

    def observed(b, f):
        c = _DC.get(b)
        if b not in tmj[f] or c is None: return None
        return tmj[f][b]["validity"] and (c in tmj[f]) and tmj[f][c]["validity"]
    Fc = [{"index": f["index"], "timestamp": f["timestamp"], "rotations": dict(f["rotations"]), "repair": {}}
          for f in frames]
    for b in bones:
        miss = [f for f in range(n) if observed(b, f) is False]
        if not miss: continue
        Q = {f: np.array(frames[f]["rotations"][b]) for f in range(n)}
        i = 0
        while i < len(miss):
            j = i
            while j + 1 < len(miss) and miss[j + 1] == miss[j] + 1: j += 1
            g0, g1 = miss[i], miss[j]
            prev = g0 - 1 if g0 - 1 >= 0 and observed(b, g0 - 1) else None
            nxt = g1 + 1 if g1 + 1 < n and observed(b, g1 + 1) else None
            for k in range(g0, g1 + 1):
                if prev is not None and nxt is not None and ang(Q[prev], Q[nxt]) <= LARGE:
                    q = slerp(Q[prev], Q[nxt], (k - prev) / (nxt - prev)); st = "interpolated"
                elif prev is not None or nxt is not None:
                    q = Q[prev if prev is not None else nxt]; st = "held"
                else:
                    q = Q[k]; st = "original_missing"
                Fc[k]["rotations"][b] = [round(float(c), 6) for c in q / np.linalg.norm(q)]
                Fc[k]["repair"][b] = st
            i = j + 1
    return Fc


def main(argv):
    ap = argparse.ArgumentParser(); ap.add_argument("--save"); a = ap.parse_args(argv[1:])
    tm = json.load(open(TMOT / "target_motion.v1.json"))
    art, errs, rest, order = build(tm)               # stabilized swing (in memory)
    stable = repair(art["frames"], tm, order)
    prev = json.load(open(TMOT / "target_rotations_temporal.v1.json"))  # 2E result = "before"

    out = {"meta": {**art["meta"], "schema": "target_rotations_stable.v1", "solver_version": "2F-stable-swing",
                    "source_artifact": "target_motion.v1.json", "temporal_repair": "2E policy re-applied",
                    "previous_artifact": "target_rotations_temporal.v1.json"}, "frames": stable}
    json.dump(out, open(TMOT / "target_rotations_stable.v1.json", "w"))

    before, after = scan(prev["frames"]), scan(stable)
    wb = max(before, key=lambda b: before[b][1]); wa = max(after, key=lambda b: after[b][1])
    print(f"fallback events={art['meta']['fallback_count']}  bones={art['meta']['fallback_bones']}")
    print(f"fallback frames(sample)={sorted({f for f,_ in art['meta']['fallback_events']})}")
    print(f"BEFORE(2E) worst jump: {wb} {before[wb][1]:.1f}deg @f{before[wb][2]}")
    print(f"AFTER(2F)  worst jump: {wa} {after[wa][1]:.1f}deg @f{after[wa][2]}")
    print(f"rightRingIntermediate max jump BEFORE={before['rightRingIntermediate'][1]:.1f} "
          f"AFTER={after['rightRingIntermediate'][1]:.1f}")
    # newly-introduced jumps: bones where after>before+20 and not a gap boundary
    worse = [b for b in after if after[b][1] > before[b][1] + 20]
    print(f"bones with NEW larger jumps (>+20deg): {worse or 'none'}")
    body = [b for b in after if b.startswith('left') or b in ('hips','spine','chest','neck','head') or 'Leg' in b or 'Foot' in b]
    print(f"max jump among left/body/legs: {max(after[b][1] for b in body):.1f}deg")

    # FK directional over observed frames (compare to 2D ~0)
    def fk_dir(frames):
        e = []
        for fi, f in enumerate(tm["frames"]):
            P = {b: (np.array(j["position"]) if j["position"] else None) for b, j in f["joints"].items()}
            R = frames[fi]["rotations"]; fp, fr = {}, {}
            for b in order:
                hp = rest[b]["hparent"]; d = np.array(R[b]); rl = qmul(qconj(rest[hp]["wrot"] if hp else IDENT), rest[b]["wrot"])
                if hp is None: fr[b] = qmul(rl, d); fp[b] = P.get("hips", rest[b]["wpos"])
                else:
                    fr[b] = qmul(fr[hp], qmul(rl, d)); off = qrot(qconj(rest[hp]["wrot"]), rest[b]["wpos"] - rest[hp]["wpos"]); fp[b] = fp[hp] + qrot(fr[hp], off)
            for b in order:
                c = _DC.get(b)
                if c and P.get(b) is not None and P.get(c) is not None and c in fp:
                    od = P[c] - P[b]; fd = fp[c] - fp[b]
                    if np.linalg.norm(od) > 1e-6 and np.linalg.norm(fd) > 1e-6:
                        e.append(math.degrees(math.acos(np.clip(np.dot(od, fd) / (np.linalg.norm(od) * np.linalg.norm(fd)), -1, 1))))
        return np.array(e)
    fe = fk_dir(stable)
    print(f"FK directional (observed): mean={fe.mean():.2f} median={np.median(fe):.2f} max={fe.max():.2f} (2D was ~0/0/15.8)")
    allq = np.array([q for f in stable for q in f["rotations"].values()])
    print(f"norms[min={np.linalg.norm(allq,axis=1).min():.4f} max={np.linalg.norm(allq,axis=1).max():.4f}] "
          f"NaN/Inf={int(np.sum(~np.isfinite(allq)))} frames={len(stable)} fps={out['meta']['fps']} "
          f"ts_unchanged={[f['timestamp'] for f in stable]==[f['timestamp'] for f in tm['frames']]}")
    print(f"-> {TMOT}/target_rotations_stable.v1.json")

    if a.save:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        n = len(stable)
        fig, ax = plt.subplots(figsize=(11, 4))
        for b, col in (("rightRingIntermediate", "tab:purple"), ("rightHand", "tab:red")):
            rb = [ang(np.array(prev["frames"][i-1]["rotations"][b]), np.array(prev["frames"][i]["rotations"][b])) for i in range(1, n)]
            ra = [ang(np.array(stable[i-1]["rotations"][b]), np.array(stable[i]["rotations"][b])) for i in range(1, n)]
            ax.plot(range(1, n), rb, col, ls="--", alpha=.6, label=f"{b} 2E")
            ax.plot(range(1, n), ra, col, lw=2, label=f"{b} 2F")
        for g in (14, 15, 16, 42, 43, 44): ax.axvspan(g-.5, g+.5, color="gray", alpha=.15)
        ax.axvline(41, color="k", ls=":", lw=.8)
        ax.set_xlabel("frame"); ax.set_ylabel("frame-to-frame rotation (deg)")
        ax.set_title("Step 2F — right-hand angular change: 2E (dashed) vs 2F stabilized (solid)")
        ax.legend(fontsize=8); fig.savefig(a.save, dpi=100, bbox_inches="tight"); print("saved", a.save)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
