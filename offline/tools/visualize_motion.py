"""Offline motion visualizer (read-only debug tool).

    python offline/tools/visualize_motion.py --clip MVI_0029 --stage normalized
    python offline/tools/visualize_motion.py --clip MVI_0029 --compare skeletal normalized
    ...add --save out.png for headless, else arrow keys step frames, q quits.

Draws each stage's skeleton: bones as lines, bone names, and per-bone LOCAL axes
from the stored rotation (red=X green=Y blue=Z). Prints root orientation, hips
position, torso-forward, mean confidence. Purpose: find the first stage whose
pose is physically wrong. Does NOT modify the pipeline.
"""
from __future__ import annotations
import argparse, glob, json, math, sys
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt

OFF = Path(__file__).resolve().parents[1] / "output"
DIRS = {"pose": "poses", "skeletal": "motions", "normalized": "normalized", "retargeted": "retargeted"}


def _find(stage, clip):
    hits = [p for p in glob.glob(str(OFF / DIRS[stage] / "*.json")) if clip.lower() in Path(p).name.lower()]
    return json.load(open(hits[0])) if hits else None


def _qrot(q, v):
    if q is None:
        return np.array(v, float)
    x, y, z, w = q
    t = 2 * np.cross([x, y, z], v)
    return np.array(v) + w * t + np.cross([x, y, z], t)


def frame(stage, clip, i):
    """Return (points{name:xyz}, edges[(a,b)], rots{name:quat|None}, stats)."""
    d = _find(stage, clip)
    if d is None:
        sys.exit(f"no {stage} file for {clip}")
    if stage == "pose":
        lm = d["frames"][i % len(d["frames"])]["landmarks"]
        pts = {k: np.array([v["x"], -v["y"], v["z"]]) for k, v in lm.items()
               if k.startswith("POSE_") and ("SHOULDER" in k or "ELBOW" in k or "WRIST" in k
               or "HIP" in k or "KNEE" in k or "NOSE" in k)}
        E = [("POSE_LEFT_SHOULDER","POSE_RIGHT_SHOULDER"),("POSE_LEFT_SHOULDER","POSE_LEFT_ELBOW"),
             ("POSE_LEFT_ELBOW","POSE_LEFT_WRIST"),("POSE_RIGHT_SHOULDER","POSE_RIGHT_ELBOW"),
             ("POSE_RIGHT_ELBOW","POSE_RIGHT_WRIST"),("POSE_LEFT_HIP","POSE_RIGHT_HIP"),
             ("POSE_LEFT_SHOULDER","POSE_LEFT_HIP"),("POSE_RIGHT_SHOULDER","POSE_RIGHT_HIP")]
        edges = [(a, b) for a, b in E if a in pts and b in pts]
        return pts, edges, {}, {"conf": None, "hips": None, "root": None}

    if stage == "retargeted":  # rotations only -> anchor axes on the normalized skeleton
        pts, edges, _, _ = frame("normalized", clip, i)
        rots = {b: (d["tracks"][b][i % len(d["tracks"][b])] if b in d["tracks"] else None) for b in pts}
        root = d["tracks"]["hips"][i % len(d["tracks"]["hips"])]
        return pts, edges, rots, {"conf": d.get("confidence"), "hips": d["hips_translation"][0], "root": root}

    # skeletal / normalized: FK by summing world-space offsets (parent-first order)
    bones = d["frames"][i % len(d["frames"])]["bones"]
    pos, rots, conf = {}, {}, []
    for b in bones:
        p = pos.get(b["parent"], np.zeros(3))
        # y is up-negated so image-space Y-down renders upright
        lp = np.array(b["local_position"]) * np.array([1, -1, 1])
        pos[b["name"]] = p + lp
        rots[b["name"]] = b["local_rotation"]
        conf.append(b["confidence"])
    edges = [(b["parent"], b["name"]) for b in bones if b["parent"]]
    hips = pos.get("hips", np.zeros(3))
    return pos, edges, rots, {"conf": float(np.mean(conf)), "hips": hips.tolist(),
                              "root": next((b["local_rotation"] for b in bones if b["name"] == "hips"), None)}


def draw(ax, stage, clip, i):
    pts, edges, rots, st = frame(stage, clip, i)
    for a, b in edges:
        p, q = pts[a], pts[b]
        ax.plot(*zip(p, q), c="k", lw=2)
    for name, p in pts.items():
        ax.text(*p, name.replace("POSE_", ""), fontsize=6, color="dimgray")
        q = rots.get(name)
        if q is not None:
            for e, col in zip(np.eye(3), ["r", "g", "b"]):
                d = _qrot(q, e) * 0.15
                ax.quiver(*p, *d, color=col, lw=1)
    ax.set_title(f"{stage}  frame {i}", fontsize=9)
    ax.set_box_aspect([1, 1, 1]); ax.set_xticks([]); ax.set_yticks([]); ax.set_zticks([])
    if st["root"] is not None:
        fwd = _qrot(st["root"], [0, 0, 1])
        print(f"[{stage} f{i}] hips={_r(st['hips'])} rootQ={_r(st['root'])} "
              f"torsoFwd={_r(fwd.tolist())} meanConf={st['conf']}")


def _r(v):
    return None if v is None else [round(float(c), 3) for c in v]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True)
    ap.add_argument("--stage", default="normalized")
    ap.add_argument("--compare", nargs=2)
    ap.add_argument("--frame", type=int, default=0)
    ap.add_argument("--save")
    a = ap.parse_args(argv[1:])
    stages = a.compare or [a.stage]
    state = {"i": a.frame}
    fig = plt.figure(figsize=(6 * len(stages), 6))
    axes = [fig.add_subplot(1, len(stages), k + 1, projection="3d") for k in range(len(stages))]

    def render():
        for ax, s in zip(axes, stages):
            ax.cla(); draw(ax, s, a.clip, state["i"])
        fig.canvas.draw_idle()

    def on_key(ev):
        if ev.key in ("right", "left"):
            state["i"] += 1 if ev.key == "right" else -1; render()
        elif ev.key == "q":
            plt.close(fig)

    render()
    if a.save:
        fig.savefig(a.save, dpi=110); print(f"saved {a.save}")
    else:
        fig.canvas.mpl_connect("key_press_event", on_key); plt.show()


if __name__ == "__main__":
    main(sys.argv)
