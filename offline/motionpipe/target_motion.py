"""TargetMotionSequence v1 — per-frame TARGET JOINT POSITIONS (no rotations).

Consumes source_skeleton.v1 + target_skeleton.v1 + skeleton_mapping.v1 +
calibration.v1 and produces target joint positions in VRM space.

Positions are built HIERARCHICALLY with AVATAR-PROPORTION-AWARE lengths:

    direction   = R * normalize(observed_child - observed_parent)   # R = source->target frame align
    target_child = target_parent + direction * avatar_rest_bone_length

i.e. each bone keeps the OBSERVED direction but is placed at the actual
AvatarSample_C rest bone length (not a single global scale). Directions are NOT
altered to fit lengths (R is a fixed rotation, angle-preserving). No IK, no
quaternions, no VRMA. Source artifacts are never modified.
"""
from __future__ import annotations

import numpy as np

SCHEMA_VERSION = "target_motion.v1"

# source fingertips have no VRM tip bone; carried as non-VRM validation joints.
_TIPS = {f"{s}{f}TIP": f"{s}{f}TIP"
         for s in ("left", "right") for f in ("Thumb", "Index", "Middle", "Ring", "Pinky")}
# tip -> distal VRM bone (Little <- Pinky); the distal bone aims at this tip.
_TIP_DISTAL = {f"{s}{sf}TIP": f"{s}{vf}Distal" for s in ("left", "right")
               for vf, sf in (("Thumb", "Thumb"), ("Index", "Index"), ("Middle", "Middle"),
                              ("Ring", "Ring"), ("Little", "Pinky"))}


def _median(frames, joint):
    pts = [f["joints"][joint][:3] for f in frames if f["joints"].get(joint)]
    return np.median(np.array(pts), axis=0) if pts else None


def _body_frame(up, lr):
    up = up / np.linalg.norm(up)
    fwd = np.cross(lr, up); fwd /= np.linalg.norm(fwd)
    right = np.cross(up, fwd); right /= np.linalg.norm(right)
    return np.column_stack([right, up, fwd])   # columns = basis vectors


def build_target_motion(src: dict, tgt: dict, mapping: dict, calib: dict) -> dict:
    M = {t: s for t, s in mapping["map"].items() if s is not None}
    F = src["frames"]

    hips_s, chest_s = _median(F, "hips"), _median(F, "chest")
    ls, rs = _median(F, "leftShoulder"), _median(F, "rightShoulder")
    tp = {b["name"]: np.array(b["rest_world"]) for b in tgt["bones"]}
    tparent = {b["name"]: b["parent"] for b in tgt["bones"]}
    S = _body_frame(chest_s - hips_s, rs - ls)
    T = _body_frame(tp["chest"] - tp["hips"], tp["rightUpperArm"] - tp["leftUpperArm"])
    R = T @ S.T
    hips_t = tp["hips"]

    # nearest MAPPED humanoid ancestor (skips unmapped bones e.g. shoulder/upperChest)
    def mapped_parent(b):
        p = tparent.get(b)
        while p is not None and p not in M:
            p = tparent.get(p)
        return p

    def depth(b):
        d, p = 0, tparent.get(b)
        while p is not None:
            d += 1; p = tparent.get(p)
        return d

    pp = {b: mapped_parent(b) for b in M if b != "hips"}
    restlen = {b: float(np.linalg.norm(tp[b] - tp[pp[b]])) for b in pp if pp[b] is not None}
    m_order = sorted([b for b in M if b != "hips" and pp.get(b) is not None], key=depth)

    def obs(fj, name):
        v = fj.get(name)
        return np.array(v[:3]) if v else None

    frames = []
    for f in F:
        fj = f["joints"]
        pos = {"hips": hips_t.copy()} if fj.get(M.get("hips", "hips")) else {"hips": None}
        # body/arm/leg/finger bones, parent-first, avatar-rest lengths
        for b in m_order:
            par = pp[b]
            oB, oP = obs(fj, M[b]), obs(fj, M[par])
            base = pos.get(par)
            if base is None or oB is None or oP is None:
                pos[b] = None
                continue
            d = R @ (oB - oP); n = np.linalg.norm(d)
            pos[b] = base + (d / n) * restlen[b] if n > 1e-9 else base.copy()
        # fingertips: aim distal bone at observed tip, avatar distal length
        for tip, distal in _TIP_DISTAL.items():
            base = pos.get(distal)
            oT, oD = obs(fj, tip), obs(fj, M.get(distal, ""))
            if base is None or oT is None or oD is None:
                pos[tip] = None
                continue
            d = R @ (oT - oD); n = np.linalg.norm(d)
            pos[tip] = base + (d / n) * restlen.get(distal, 0.02) if n > 1e-9 else base.copy()

        J = {}
        for tb, sj in {**M, **_TIPS}.items():
            p = pos.get(tb); sp = fj.get(sj); is_bone = tb in M
            if p is None:
                J[tb] = {"position": None, "validity": False, "source_joint": sj, "confidence": None,
                         "vrm_bone": is_bone, "reason": "source missing" if sp is None else "parent chain missing"}
            else:
                J[tb] = {"position": [round(float(c), 5) for c in p], "validity": True,
                         "source_joint": sj, "confidence": (sp[3] if sp else None), "vrm_bone": is_bone}
        frames.append({"index": f["index"], "timestamp": f["timestamp"], "joints": J})

    m = src["meta"]
    meta = {
        "schema": SCHEMA_VERSION, "represents": "TARGET JOINT POSITIONS (not rotations)",
        "source_video": m["source_video"], "fps": m["fps"], "frame_count": len(frames),
        "duration": m["duration"], "coordinate_space": tgt["coordinate_space"],
        "target_skeleton": tgt["source_asset"], "calibration_id": calib["schema"],
        "construction": "hierarchical: observed direction (R-aligned) * AVATAR rest bone length; "
        "no global scale; directions unchanged",
        "transform": {"operation": "SourceToTargetCalibration",
                      "R": [[round(float(c), 6) for c in row] for row in R],
                      "det_R": round(float(np.linalg.det(R)), 4),
                      "hips_source_ref": [round(float(c), 5) for c in hips_s],
                      "hips_target_rest": [round(float(c), 5) for c in hips_t]},
        "facing_method": "anatomical body frame [right,up,fwd]; R = T . S^T aligns source->target",
    }
    return {"meta": meta, "frames": frames}
