"""CLI: target_motion.v1 -> target_rotations.v1 + FK validation + overlap viz.

    python offline/tools/build_target_rotations.py --save out.png
No VRMA / IK / runtime changes.
"""
from __future__ import annotations
import argparse, glob, json, math, sys
from pathlib import Path
import numpy as np

OFF = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(OFF))
from motionpipe.target_rotations import build, qmul, qconj, IDENT  # noqa: E402

TM = OFF / "output" / "target_motion" / "target_motion.v1.json"
OUT = OFF / "output" / "target_motion"


def main(argv):
    ap = argparse.ArgumentParser(); ap.add_argument("--save"); a = ap.parse_args(argv[1:])
    tm = json.load(open(TM))
    art, errs, rest, order = build(tm)
    json.dump(art, open(OUT / "target_rotations.v1.json", "w"))

    # quaternion round-trip sanity: conj(p)*(p*c) == c
    import numpy.random as R
    rp = np.array([.1, .3, -.2, .9]); rp /= np.linalg.norm(rp)
    rc = np.array([.4, -.1, .2, .88]); rc /= np.linalg.norm(rc)
    rt = float(np.max(np.abs(qmul(qconj(rp), qmul(rp, rc)) - rc)))

    F = art["frames"]
    allq = np.array([q for f in F for q in f["rotations"].values()])
    norms = np.linalg.norm(allq, axis=1)
    nan = int(np.sum(~np.isfinite(allq)))
    # temporal continuity: max per-bone frame-to-frame quat angle
    maxjump = 0.0
    for b in F[0]["rotations"]:
        for i in range(1, len(F)):
            q0 = np.array(F[i-1]["rotations"][b]); q1 = np.array(F[i]["rotations"][b])
            d = abs(float(np.clip(np.dot(q0, q1), -1, 1))); maxjump = max(maxjump, 2*math.degrees(math.acos(d)))

    print(f"schema={art['meta']['schema']} frames={art['meta']['frame_count']} fps={art['meta']['fps']}")
    print(f"quat round-trip err={rt:.2e}  norms[min={norms.min():.4f} max={norms.max():.4f}]  NaN/Inf={nan}")
    print(f"max frame-to-frame bone rotation = {maxjump:.1f}° (temporal continuity)")
    print("--- FK POSITIONAL error vs target_motion (meters), per region ---")
    allе = []
    for reg in ("torso", "arm", "hand", "finger", "leg"):
        e = errs.get(reg, [])
        if e:
            allе += e
            print(f"  {reg:7} n={len(e):5} mean={np.mean(e):.4f} median={np.median(e):.4f} max={np.max(e):.4f}")
    allе = np.array(allе)
    print(f"  ALL     n={len(allе)} mean={allе.mean():.4f} median={np.median(allе):.4f} max={allе.max():.4f}")
    # directional check: does FK reproduce bone DIRECTIONS (rotation correctness, morphology-independent)?
    print(f"-> {OUT}/target_rotations.v1.json")

    if a.save:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        # rebuild FK positions for viz overlay
        from motionpipe.target_rotations import qrot
        tmF = tm["frames"]
        # hierarchy edges among bones we have
        thier = [(rest[b]["hparent"], b) for b in order if rest[b]["hparent"] in rest]
        idx = [0, len(F)//3, len(F)//2, len(F)-1]
        fig, axes = plt.subplots(1, 4, figsize=(14, 4.2))
        for ax, i in zip(axes, idx):
            # observed target positions
            Pj = tmF[i]["joints"]
            for p, c in thier:
                pa = Pj.get(p, {}).get("position"); pb = Pj.get(c, {}).get("position")
                if pa and pb: ax.plot([pa[0], pb[0]], [pa[1], pb[1]], c="tab:blue", lw=1.4, alpha=.5)
            # FK reconstruction
            P = {b: (np.array(j["position"]) if j["position"] else None) for b, j in Pj.items()}
            fkpos, fkrot = {}, {}
            for b in order:
                hp = rest[b]["hparent"]; d = np.array(F[i]["rotations"][b])
                rl = qmul(qconj(rest[hp]["wrot"] if hp else IDENT), rest[b]["wrot"])
                if hp is None:
                    fkrot[b] = qmul(rl, d); fkpos[b] = P.get("hips", rest[b]["wpos"])
                else:
                    fkrot[b] = qmul(fkrot[hp], qmul(rl, d))
                    off = qrot(qconj(rest[hp]["wrot"]), rest[b]["wpos"]-rest[hp]["wpos"])
                    fkpos[b] = fkpos[hp] + qrot(fkrot[hp], off)
            for p, c in thier:
                ax.plot([fkpos[p][0], fkpos[c][0]], [fkpos[p][1], fkpos[c][1]], c="tab:red", lw=0.9)
            ax.set_title(f"f{i}", fontsize=9); ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
        fig.suptitle("Step 2D — target positions (blue) vs FK from derived rotations (red)", fontsize=10)
        fig.savefig(a.save, dpi=100); print("saved", a.save)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
