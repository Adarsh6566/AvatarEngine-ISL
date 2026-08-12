"""READ-ONLY 3-panel motion debugger: video+landmarks | source skeleton | FK avatar.

    python offline/tools/compare_motion.py            # PNGs (0,10..60)+contact+JSON+summary
    python offline/tools/compare_motion.py --frame 41 # single frame
Nothing in the mapping pipeline is modified.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import numpy as np

OFF = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(OFF))
from motionpipe.motion_debugger import load, analyze, fk_frame  # noqa: E402
from motionpipe.source_skeleton import HIERARCHY as SHIER  # noqa: E402
from motionpipe.target_rotations import _DC  # noqa: E402

VIDEO = OFF / "datasets" / "isl_greeting" / "hello" / "MVI_0029.MOV"
OUT = OFF / "output" / "debug"
_FING = [("Thumb", "Thumb"), ("Index", "Index"), ("Middle", "Middle"), ("Ring", "Ring"), ("Little", "Pinky")]


def thier(rest, order, present):
    e = [(rest[b]["hparent"], b) for b in order if rest[b]["hparent"] in present and b in present]
    for s in ("left", "right"):
        for vf, sf in _FING:
            e.append((f"{s}{vf}Distal", f"{s}{sf}TIP"))
    return e


def panel_src(ax, src, i, w, h):
    import cv2
    cap = cv2.VideoCapture(str(VIDEO)); cap.set(cv2.CAP_PROP_POS_FRAMES, i)
    ok, bgr = cap.read(); cap.release()
    if ok:
        ax.imshow(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    J = src["frames"][i]["joints"]
    for p, c in SHIER:
        a, b = J.get(p), J.get(c)
        if a and b:
            col = "lime" if "left" in c.lower() and any(k in c for k in ("Thumb","Index","Middle","Ring","Pinky","Hand")) \
                else "red" if "right" in c.lower() and any(k in c for k in ("Thumb","Index","Middle","Ring","Pinky","Hand")) else "cyan"
            ax.plot([a[0]*w, b[0]*w], [a[1]*h, b[1]*h], c=col, lw=1)
    rh = any(J.get(k) for k in ("rightHandWrist",))
    ax.set_title(f"video+landmarks f{i}" + ("" if rh else "  [R-hand MISSING]"), fontsize=8)
    ax.set_xticks([]); ax.set_yticks([])


def panel_skel(ax, J, edges, getp, title, cols=True):
    for p, c in edges:
        a, b = getp(J, p), getp(J, c)
        if a is not None and b is not None:
            col = "tab:green" if "left" in c and any(k in c for k in ("Thumb","Index","Middle","Ring","Little","Hand","TIP")) \
                else "tab:red" if "right" in c and any(k in c for k in ("Thumb","Index","Middle","Ring","Little","Hand","TIP")) else "black"
            ax.plot([a[0], b[0]], [a[1], b[1]], c=col if cols else "0.5", lw=0.9)
    ax.set_title(title, fontsize=8); ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])


def render(i, src, tm, rot, rest, order, fks, path):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(15, 5))
    panel_src(a1, src, i, 1920, 1080)
    Js = src["frames"][i]["joints"]
    panel_skel(a2, Js, SHIER, lambda J, k: (np.array([J[k][0], -J[k][1]]) if J.get(k) else None),
               f"source skeleton f{i} (img space)")
    fp = fks[i]; present = set(fp)
    edges = thier(rest, order, present)
    # FK avatar (VRM x,y) + faint target positions for length comparison
    Tj = tm["frames"][i]["joints"]
    panel_skel(a3, Tj, edges, lambda J, k: (np.array(J[k]["position"][:2]) if J.get(k, {}).get("position") else None),
               f"FK avatar f{i} (VRM space)  [target=faint]", cols=False)
    for p, c in edges:
        if p in fp and c in fp:
            col = "tab:green" if "left" in c and any(k in c for k in ("Thumb","Index","Middle","Ring","Little","Hand","TIP")) \
                else "tab:red" if "right" in c and any(k in c for k in ("Thumb","Index","Middle","Ring","Little","Hand","TIP")) else "black"
            a3.plot([fp[p][0], fp[c][0]], [fp[p][1], fp[c][1]], c=col, lw=1.2)
    fig.savefig(path, dpi=90, bbox_inches="tight"); plt.close(fig)


def main(argv):
    ap = argparse.ArgumentParser(); ap.add_argument("--frame", type=int); a = ap.parse_args(argv[1:])
    src, tm, rot, rest, order = load()
    fks, rep = analyze(src, tm, rot, rest, order)
    OUT.mkdir(parents=True, exist_ok=True)
    frames = [a.frame] if a.frame is not None else [0, 10, 20, 30, 40, 50, 60]
    for i in frames:
        render(i, src, tm, rot, rest, order, fks, OUT / f"frame_{i:02d}.png")
    # contact sheet
    if a.frame is None:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        n = len(fks); cols = 9; rows = (n + cols - 1) // cols
        fig, axes = plt.subplots(rows, cols, figsize=(cols * 1.5, rows * 1.7))
        edgesf = thier(rest, order, set(fks[0]))
        for i in range(rows * cols):
            ax = axes.flat[i]
            if i < n:
                for p, c in edgesf:
                    if p in fks[i] and c in fks[i]:
                        col = "tab:red" if "right" in c and any(k in c for k in ("Hand","Thumb","Index","Middle","Ring","Little","TIP")) else \
                            "tab:green" if "left" in c and any(k in c for k in ("Hand","Thumb","Index","Middle","Ring","Little","TIP")) else "k"
                        ax.plot([fks[i][p][0], fks[i][c][0]], [fks[i][p][1], fks[i][c][1]], c=col, lw=0.5)
                ax.set_title(str(i), fontsize=6)
            ax.set_aspect("equal"); ax.set_xticks([]); ax.set_yticks([])
        fig.suptitle("FK avatar contact sheet — 63 frames", fontsize=10)
        fig.savefig(OUT / "contact_sheet.png", dpi=90, bbox_inches="tight"); plt.close(fig)
    json.dump(rep, open(OUT / "diagnostic_report.json", "w"), indent=1, default=str)

    print(f"frames={rep['frames']} fps={rep['fps']}")
    print("=== FK directional error vs TARGET (deg) — after-FK rotation fidelity ===")
    for r, s in rep["dir_err_by_region"].items():
        print(f"  {r:7} mean={s['mean']:5.2f} max={s['max']:6.2f} @f{s['worst_frame']} ({s['worst_bone']})")
    print("=== length ratio target/avatar (morphology) — worst 6 ===")
    for b, (tl, rl, ra) in sorted(rep["length_ratio"].items(), key=lambda kv: -abs((kv[1][2] or 1) - 1))[:6]:
        print(f"  {b:16} target={tl} avatar_rest={rl} ratio={ra}")
    print("=== rotation discontinuities (raw, top 5) ===")
    for b, (mx, f) in rep["rotation_discontinuity_top"][:5]:
        print(f"  {b:22} {mx:6.1f}deg @f{f}")
    print("=== where does the 172deg finger jump live? (dir discontinuity by stage) ===")
    print("  SOURCE space top:", rep["source_dir_disc_top"][:3])
    print("  TARGET space top:", rep["target_dir_disc_top"][:3])
    print(f"-> {OUT}/ (frame_*.png, contact_sheet.png, diagnostic_report.json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
