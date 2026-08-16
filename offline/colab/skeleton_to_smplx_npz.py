"""source_skeleton.v1 (joint POSITIONS) -> SMPL-X poses NPZ  (Route 1, Colab).

Converts the MediaPipe skeleton stream produced by `pipeline/` into an
AMASS-style SMPL-X NPZ (`poses [N,165]`, `trans [N,3]`) that both the `smplx`
Python package AND the Blender SMPL-X add-on's animation loader can consume.

METHOD (no optimization, no IK): forward-kinematic SWING extraction. SMPL-X rest
joint frames are all identity, so each joint's pose parameter is simply the local
rotation that turns its REST bone direction onto the OBSERVED bone direction,
expressed in its parent's frame:

    pose_j = qfromto( rest_dir_j ,  Rparent⁻¹ · observed_dir_j )
    Rworld_j = Rworld_parent · pose_j        (walk parents before children)

Ported 1:1 from the project's round-trip-verified conventions in
offline/motionpipe/target_rotations.py (quats are x,y,z,w, Hamilton mul).

HONEST LIMITS (inherent to the input, not the method):
  * SWING ONLY — no twist is recovered (positions can't constrain axial roll).
  * Fingers: the pipeline captured 2 joints/finger, so only the PROXIMAL bend is
    driven; the middle/distal finger joints stay at rest. Coarse finger motion.
  * MediaPipe depth is cheap-3D, so out-of-plane pose is approximate.
  * global translation is the observed hips path scaled to metres — approximate.

This file is standalone and additive. It imports nothing from the app. Run it in
Colab where `smplx` + the neutral model are available. VALIDATE with the render
cell before trusting the output (see the module docstring at the bottom).
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

# --- quaternion helpers (x,y,z,w) — same convention as target_rotations.py ----
IDENT = np.array([0.0, 0.0, 0.0, 1.0])


def qmul(a, b):
    ax, ay, az, aw = a; bx, by, bz, bw = b
    return np.array([aw*bx+ax*bw+ay*bz-az*by, aw*by-ax*bz+ay*bw+az*bx,
                     aw*bz+ax*by-ay*bx+az*bw, aw*bw-ax*bx-ay*by-az*bz])


def qconj(q): return np.array([-q[0], -q[1], -q[2], q[3]])
def qnorm(q):
    n = np.linalg.norm(q)
    return q / n if n > 1e-12 else IDENT.copy()


def qrot(q, v):
    x, y, z, w = q
    t = 2 * np.cross([x, y, z], v)
    return v + w * t + np.cross([x, y, z], t)


def qfromto(a, b):
    a = a / (np.linalg.norm(a) or 1.0); b = b / (np.linalg.norm(b) or 1.0)
    d = float(np.clip(np.dot(a, b), -1, 1))
    if d > 0.999999:
        return IDENT.copy()
    if d < -0.999999:
        ax = np.cross([1, 0, 0], a)
        if np.dot(ax, ax) < 1e-6:
            ax = np.cross([0, 1, 0], a)
        ax = ax / np.linalg.norm(ax)
        return np.array([ax[0], ax[1], ax[2], 0.0])
    ax = np.cross(a, b)
    return qnorm(np.array([ax[0], ax[1], ax[2], 1 + d]))


def q_to_axisangle(q):
    """Unit quaternion (x,y,z,w) -> axis-angle 3-vector (SMPL-X pose param)."""
    q = qnorm(q)
    w = float(np.clip(q[3], -1, 1))
    ang = 2 * math.acos(w)
    s = math.sqrt(max(0.0, 1 - w * w))
    if s < 1e-8:
        return np.zeros(3)
    return (ang * q[:3] / s).astype(np.float32)


def q_from_R(R):
    t = np.trace(R)
    if t > 0:
        s = np.sqrt(t + 1) * 2; w = .25 * s
        x = (R[2, 1] - R[1, 2]) / s; y = (R[0, 2] - R[2, 0]) / s; z = (R[1, 0] - R[0, 1]) / s
    else:
        i = int(np.argmax([R[0, 0], R[1, 1], R[2, 2]])); j = (i + 1) % 3; k = (i + 2) % 3
        s = np.sqrt(R[i, i] - R[j, j] - R[k, k] + 1) * 2; q = [0, 0, 0]
        w = (R[k, j] - R[j, k]) / s; q[i] = .25 * s
        q[j] = (R[j, i] + R[i, j]) / s; q[k] = (R[k, i] + R[i, k]) / s
        x, y, z = q
    return qnorm(np.array([x, y, z, w]))


def _frame(up, lr):
    up = up / np.linalg.norm(up); f = np.cross(lr, up); f /= np.linalg.norm(f)
    r = np.cross(up, f); r /= np.linalg.norm(r)
    return np.column_stack([r, up, f])


# --- SMPL-X kinematic tree (55 joints): parent index -------------------------
SMPLX_PARENT = [-1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 12, 13, 14, 16, 17,
                18, 19, 15, 15, 15,
                20, 25, 26, 20, 28, 29, 20, 31, 32, 20, 34, 35, 20, 37, 38,
                21, 40, 41, 21, 43, 44, 21, 46, 47, 21, 49, 50, 21, 52, 53]

# For each SMPL-X joint we drive: (rest_child_smplx, obs_self_pipeline, obs_child_pipeline)
# rest_child_smplx = the kinematic child used for the REST bone direction.
# obs_* = pipeline joint names whose positions give the OBSERVED bone direction.
# Joints absent here (jaw, eyes, spine3, finger mid/distal) stay at REST (pose 0).
DRIVE = {
    1: (4, "lHip", "lKnee"),   4: (7, "lKnee", "lAnkle"),   7: (10, "lAnkle", "lFoot"),
    2: (5, "rHip", "rKnee"),   5: (8, "rKnee", "rAnkle"),   8: (11, "rAnkle", "rFoot"),
    3: (6, "spine", "chest"),  6: (12, "chest", "neck"),    12: (15, "neck", "head"),
    13: (16, "chest", "lShoulder"), 14: (17, "chest", "rShoulder"),
    16: (18, "lShoulder", "lElbow"), 18: (20, "lElbow", "lWrist"), 20: (25, "lWrist", "lHand"),
    17: (19, "rShoulder", "rElbow"), 19: (21, "rElbow", "rWrist"), 21: (40, "rWrist", "rHand"),
    # fingers — proximal bend only (2 captured joints per finger)
    25: (26, "lIndex1", "lIndex2"), 28: (29, "lMiddle1", "lMiddle2"),
    31: (32, "lPinky1", "lPinky2"), 34: (35, "lRing1", "lRing2"), 37: (38, "lThumb1", "lThumb2"),
    40: (41, "rIndex1", "rIndex2"), 43: (44, "rMiddle1", "rMiddle2"),
    46: (47, "rPinky1", "rPinky2"), 49: (50, "rRing1", "rRing2"), 52: (53, "rThumb1", "rThumb2"),
}

# pose vector slot (offset into the 165 vector) for each SMPL-X joint index.
def pose_slot(j: int) -> int | None:
    if j == 0:   return 0            # global_orient
    if 1 <= j <= 21:  return 3 + (j - 1) * 3     # body_pose
    if j == 22:  return 66           # jaw
    if j in (23, 24): return None    # eyes -> zeros
    if 25 <= j <= 39: return 75 + (j - 25) * 3   # left hand
    if 40 <= j <= 54: return 120 + (j - 40) * 3  # right hand
    return None


def load_rest_joints(model_path: str, model_type="smplx"):
    """Rest (zero-pose) SMPL-X joint positions [55,3] via the smplx package."""
    import torch, smplx
    m = smplx.create(model_path, model_type=model_type, gender="neutral",
                     use_pca=False, flat_hand_mean=True, batch_size=1)
    with torch.no_grad():
        out = m(return_full_pose=True)
    J = out.joints[0].cpu().numpy()[:55]
    return J.astype(np.float64)


def _pos(frame_joints, name):
    v = frame_joints.get(name)
    if v is None:
        return None
    p = np.array(v[:3], dtype=np.float64)
    return p if np.isfinite(p).all() else None


def convert(skeleton_json: str, rest_J: np.ndarray, fps_override: float | None = None):
    d = json.load(open(skeleton_json))
    meta = d["meta"]; frames = d["frames"]
    fps = fps_override or float(meta.get("fps", 25.0))
    N = len(frames)

    # metre scale: SMPL-X rest hip->head length / view-space unit (=1.0 hip->head)
    rest_scale = float(np.linalg.norm(rest_J[15] - rest_J[0]))  # head - pelvis

    poses = np.zeros((N, 165), dtype=np.float32)
    trans = np.zeros((N, 3), dtype=np.float32)
    driven_counts = np.zeros(N, dtype=np.int32)

    for fi, f in enumerate(frames):
        P = f["joints"]
        Rw = {}  # world rotation per SMPL-X joint index

        # root (pelvis): anatomical frame from observed torso
        hips, chest = _pos(P, "hips"), _pos(P, "chest")
        lS, rS = _pos(P, "lShoulder"), _pos(P, "rShoulder")
        if hips is not None and chest is not None and lS is not None and rS is not None:
            Rw[0] = q_from_R(_frame(chest - hips, rS - lS))
        else:
            Rw[0] = IDENT.copy()
        poses[fi, 0:3] = q_to_axisangle(Rw[0])
        if hips is not None:
            trans[fi] = (hips * rest_scale).astype(np.float32)

        # children: walk in index order (parents always precede children here)
        for j in range(1, 55):
            par = SMPLX_PARENT[j]
            Rw[j] = Rw.get(par, IDENT).copy()      # default: inherit parent (pose=0)
            spec = DRIVE.get(j)
            slot = pose_slot(j)
            if spec is None or slot is None:
                continue
            rest_child, self_name, child_name = spec
            ps, pc = _pos(P, self_name), _pos(P, child_name)
            if ps is None or pc is None:
                continue
            obs_dir = pc - ps
            if np.linalg.norm(obs_dir) < 1e-6:
                continue
            rest_dir = rest_J[rest_child] - rest_J[j]
            # bring observed direction into the parent's frame, then local swing
            obs_local = qrot(qconj(Rw[par]), obs_dir)
            pose_q = qfromto(rest_dir, obs_local)
            Rw[j] = qmul(Rw[par], pose_q)
            poses[fi, slot:slot + 3] = q_to_axisangle(pose_q)
            driven_counts[fi] += 1

    return {
        "poses": poses, "trans": trans, "fps": fps, "N": N,
        "rest_scale": rest_scale, "driven_counts": driven_counts,
        "gloss": meta.get("gloss", ""), "source": meta.get("source_video", skeleton_json),
    }


def save_and_report(res: dict, out_path: str):
    out = Path(out_path); out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out,
             poses=res["poses"], trans=res["trans"],
             betas=np.zeros(10, np.float32), gender="neutral",
             mocap_frame_rate=np.float32(res["fps"]))
    p, t = res["poses"], res["trans"]
    print(f"saved {out}  poses {p.shape}  trans {t.shape}  fps {res['fps']}")
    print(f"  finite: poses={np.isfinite(p).all()} trans={np.isfinite(t).all()}")
    print(f"  driven joints/frame: min={res['driven_counts'].min()} "
          f"max={res['driven_counts'].max()} mean={res['driven_counts'].mean():.1f} (of ~25)")
    lh = p[:, 75:120]; rh = p[:, 120:165]
    print(f"  left-hand pose motion (std): {lh.std():.4f}   right-hand: {rh.std():.4f}")
    print(f"  body pose motion (std): {p[:, 3:66].std():.4f}")
    print(f"  rest hip->head scale (m): {res['rest_scale']:.3f}")
    print("  NOTE: swing-only, coarse fingers, camera/view-frame translation — see docstring.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skeleton", required=True, help="pipeline/outputs/*.json")
    ap.add_argument("--model-path", required=True, help="dir containing smplx/ neutral model")
    ap.add_argument("--out", required=True)
    ap.add_argument("--fps", type=float, default=None)
    a = ap.parse_args()
    rest_J = load_rest_joints(a.model_path)
    res = convert(a.skeleton, rest_J, a.fps)
    save_and_report(res, a.out)


if __name__ == "__main__":
    main()
