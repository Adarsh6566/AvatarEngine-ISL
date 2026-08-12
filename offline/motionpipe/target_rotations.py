"""target_rotations.v1 — TargetMotionSequence (positions) -> per-bone rest-relative
rotations for the ACTUAL AvatarSample_C.vrm, plus an independent FK validator.

Convention (verified by round-trip): all quats (x,y,z,w), qmul = Hamilton so that
worldRot = qmul(parentWorld, localRot). Per bone:
  restLocal   = qmul(conj(restWorld[parent]), restWorld[bone])       (from VRM rest)
  obsWorld    = qmul(swing, restWorld[bone])   swing = fromTo(restDir, obsDir)  (world)
  animLocal   = qmul(conj(obsWorld[parent]), obsWorld[bone])
  delta       = qmul(conj(restLocal), animLocal)      # animLocal = qmul(restLocal, delta)
delta is identity when the observed pose equals rest. Twist is NOT invented:
swing-only for limbs/fingers; hips uses a 2-vector anatomical frame (full 3-DOF).
Bones with no child/observation preserve rest (delta = identity).
"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import numpy as np

SCHEMA = "target_rotations.v1"
VRM = Path(__file__).resolve().parents[2] / "public" / "models" / "AvatarSample_C.vrm"
IDENT = np.array([0.0, 0.0, 0.0, 1.0])


def qmul(a, b):
    ax, ay, az, aw = a; bx, by, bz, bw = b
    return np.array([aw*bx+ax*bw+ay*bz-az*by, aw*by-ax*bz+ay*bw+az*bx,
                     aw*bz+ax*by-ay*bx+az*bw, aw*bw-ax*bx-ay*by-az*bz])


def qconj(q): return np.array([-q[0], -q[1], -q[2], q[3]])


def qrot(q, v):
    x, y, z, w = q
    t = 2*np.cross([x, y, z], v)
    return v + w*t + np.cross([x, y, z], t)


def qnorm(q): return q/np.linalg.norm(q)


def qfromto(a, b):
    d = float(np.clip(np.dot(a, b), -1, 1))
    if d > 0.999999: return IDENT.copy()
    if d < -0.999999:
        ax = np.cross([1, 0, 0], a)
        if np.dot(ax, ax) < 1e-6: ax = np.cross([0, 1, 0], a)
        ax = ax/np.linalg.norm(ax); return np.array([ax[0], ax[1], ax[2], 0.0])
    ax = np.cross(a, b); return qnorm(np.array([ax[0], ax[1], ax[2], 1+d]))


ANTIPARALLEL_DOT = -0.98   # dot(restDir,obsDir) below this (~>168.5°) = degenerate swing


def _ortho(v):
    a = np.array([1.0, 0, 0]) if abs(v[0]) < 0.9 else np.array([0, 1.0, 0])
    return np.cross(v, a)


def stable_swing(rest_dir, obs_dir, wrot):
    """Shortest-arc swing rest_dir->obs_dir, with a DETERMINISTIC fallback near
    antiparallel (where fromTo's axis is ambiguous and flips frame-to-frame).

    Fallback: rotate by the true angle about a STABLE axis = the bone's rest
    side-axis (rest orientation applied to local X, then local Z, then Y),
    projected perpendicular to rest_dir; if all are parallel, a largest-component
    orthogonal of rest_dir. Same input -> same quaternion. No twist invented.
    Returns (quat, used_fallback).
    """
    d = float(np.clip(np.dot(rest_dir, obs_dir), -1, 1))
    if d > ANTIPARALLEL_DOT:
        return qfromto(rest_dir, obs_dir), False
    axis = None
    for local in ([1.0, 0, 0], [0, 0, 1.0], [0, 1.0, 0]):
        ref = qrot(wrot, np.array(local))
        cand = ref - np.dot(ref, rest_dir) * rest_dir
        if np.linalg.norm(cand) > 1e-3:
            axis = cand; break
    if axis is None:
        axis = _ortho(rest_dir)
    axis = axis / np.linalg.norm(axis)
    ang = math.acos(d); s = math.sin(ang / 2)
    return qnorm(np.array([axis[0] * s, axis[1] * s, axis[2] * s, math.cos(ang / 2)])), True


def q_from_R(R):
    t = np.trace(R)
    if t > 0:
        s = np.sqrt(t+1)*2; w = .25*s
        x = (R[2, 1]-R[1, 2])/s; y = (R[0, 2]-R[2, 0])/s; z = (R[1, 0]-R[0, 1])/s
    else:
        i = np.argmax([R[0, 0], R[1, 1], R[2, 2]]); j = (i+1) % 3; k = (i+2) % 3
        s = np.sqrt(R[i, i]-R[j, j]-R[k, k]+1)*2; q = [0, 0, 0]
        w = (R[k, j]-R[j, k])/s; q[i] = .25*s; q[j] = (R[j, i]+R[i, j])/s; q[k] = (R[k, i]+R[i, k])/s
        x, y, z = q
    return qnorm(np.array([x, y, z, w]))


def _frame(up, lr):
    up = up/np.linalg.norm(up); f = np.cross(lr, up); f /= np.linalg.norm(f)
    r = np.cross(up, f); r /= np.linalg.norm(r)
    return np.column_stack([r, up, f])


def extract_rest(path=VRM):
    b = path.read_bytes(); o = 12; ch = {}
    while o < len(b):
        ln, ty = struct.unpack("<II", b[o:o+8]); o += 8; ch[ty] = b[o:o+ln]; o += ln
    g = json.loads(ch[0x4E4F534A]); N = g["nodes"]
    hb = g["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]
    node = {k: (v["node"] if isinstance(v, dict) else v) for k, v in hb.items()}
    bone_of = {n: k for k, n in node.items()}
    par = {}
    for i, nd in enumerate(N):
        for c in nd.get("children", []): par[c] = i
    wpos, wrot = {}, {}

    def fk(i):
        if i in wpos: return
        p = par.get(i)
        if p is None:
            wpos[i] = np.array(N[i].get("translation", [0, 0, 0]), float); wrot[i] = np.array(N[i].get("rotation", [0, 0, 0, 1]), float)
        else:
            fk(p)
            wpos[i] = wpos[p] + qrot(wrot[p], np.array(N[i].get("translation", [0, 0, 0]), float))
            wrot[i] = qmul(wrot[p], np.array(N[i].get("rotation", [0, 0, 0, 1]), float))
    for i in range(len(N)): fk(i)

    def hpar(bone):
        j = par.get(node[bone])
        while j is not None:
            if j in bone_of: return bone_of[j]
            j = par.get(j)
        return None
    rest = {bn: {"hparent": hpar(bn), "wpos": wpos[node[bn]], "wrot": wrot[node[bn]]} for bn in node}
    return rest


# direction-child per bone (data). fingers built below. None => preserve rest.
_DC = {"hips": None, "spine": "chest", "chest": "neck", "neck": "head", "head": None,
       "leftUpperArm": "leftLowerArm", "leftLowerArm": "leftHand", "leftHand": "leftMiddleProximal",
       "rightUpperArm": "rightLowerArm", "rightLowerArm": "rightHand", "rightHand": "rightMiddleProximal",
       "leftUpperLeg": "leftLowerLeg", "leftLowerLeg": "leftFoot", "leftFoot": None,
       "rightUpperLeg": "rightLowerLeg", "rightLowerLeg": "rightFoot", "rightFoot": None}
_FCHAIN = [("Thumb", "Thumb"), ("Index", "Index"), ("Middle", "Middle"), ("Ring", "Ring"), ("Little", "Pinky")]
for s in ("left", "right"):
    for vf, sf in _FCHAIN:
        if vf == "Thumb":
            seq = ["Metacarpal", "Proximal", "Distal"]
        else:
            seq = ["Proximal", "Intermediate", "Distal"]
        for a, bn in zip(seq, seq[1:]):
            _DC[f"{s}{vf}{a}"] = f"{s}{vf}{bn}"
        _DC[f"{s}{vf}{seq[-1]}"] = f"{s}{sf}TIP"   # distal -> fingertip


def build(tm: dict):
    rest = extract_rest()
    order = [b for b in _order(rest) if b in rest]
    frames_out, errs, fb = [], {}, []
    for fi, f in enumerate(tm["frames"]):
        P = {b: (np.array(j["position"]) if j["position"] else None) for b, j in f["joints"].items()}
        ow = {}
        # hips: anatomical frame from observed torso
        if all(P.get(k) is not None for k in ("hips", "chest", "leftUpperArm", "rightUpperArm")):
            ow["hips"] = q_from_R(_frame(P["chest"]-P["hips"], P["rightUpperArm"]-P["leftUpperArm"]))
        else:
            ow["hips"] = rest["hips"]["wrot"]
        for B in order:
            if B == "hips": continue
            c = _DC.get(B)
            if c and P.get(B) is not None and P.get(c) is not None:
                od = P[c]-P[B]
                # child may be a fingertip (no rest bone) -> use this bone's own rest
                # direction (from its parent) as the rest reference.
                rd = (rest[c]["wpos"]-rest[B]["wpos"]) if c in rest \
                    else (rest[B]["wpos"]-rest[rest[B]["hparent"]]["wpos"])
                if np.linalg.norm(od) > 1e-6 and np.linalg.norm(rd) > 1e-6:
                    sw, used = stable_swing(qnorm4(rd), qnorm4(od), rest[B]["wrot"])
                    ow[B] = qmul(sw, rest[B]["wrot"])
                    if used: fb.append([fi, B])
                else: ow[B] = rest[B]["wrot"]
            else: ow[B] = rest[B]["wrot"]
        # local + rest-relative delta; then FK reconstruct
        rot, fkpos, fkrot = {}, {}, {}
        for B in order:
            hp = rest[B]["hparent"]
            pw = ow.get(hp, IDENT) if hp else IDENT
            rlp = rest[hp]["wrot"] if hp else IDENT
            restLocal = qmul(qconj(rlp), rest[B]["wrot"])
            animLocal = qmul(qconj(pw), ow[B])
            delta = qnorm(qmul(qconj(restLocal), animLocal))
            rot[B] = delta
            # FK
            if hp is None:
                fkrot[B] = ow[B]; fkpos[B] = P["hips"] if P.get("hips") is not None else rest[B]["wpos"]
            else:
                fkrot[B] = qmul(fkrot[hp], qmul(restLocal, delta))
                off = qrot(qconj(rest[hp]["wrot"]), rest[B]["wpos"]-rest[hp]["wpos"])
                fkpos[B] = fkpos[hp] + qrot(fkrot[hp], off)
            if P.get(B) is not None:
                errs.setdefault(_region(B), []).append(float(np.linalg.norm(fkpos[B]-P[B])))
        frames_out.append({"index": f["index"], "timestamp": f["timestamp"],
                           "rotations": {b: [round(float(c), 6) for c in q] for b, q in rot.items()}})
    meta = {"schema": SCHEMA, "source_target_motion": "target_motion.v1.json",
            "target_skeleton": "AvatarSample_C.vrm", "fps": tm["meta"]["fps"],
            "frame_count": len(frames_out),
            "convention": "animLocal = restLocal * delta ; worldRot = parentWorld * animLocal ; quats xyzw",
            "twist": "swing-only for limbs/fingers; hips=2-vector anatomical frame; leaves preserve rest",
            "antiparallel_dot": ANTIPARALLEL_DOT,
            "fallback_method": "stable_swing: 180-ish rotation about bone rest side-axis (rest*localX, "
            "projected perp to restDir) when dot(restDir,obsDir) < threshold; deterministic, no twist",
            "fallback_events": fb, "fallback_count": len(fb),
            "fallback_bones": sorted({b for _, b in fb})}
    return {"meta": meta, "frames": frames_out}, errs, rest, order


def qnorm4(v): return v/np.linalg.norm(v)


def _order(rest):
    seen, out = set(), []
    def add(b):
        if b in seen or b not in rest: return
        hp = rest[b]["hparent"]
        if hp: add(hp)
        seen.add(b); out.append(b)
    for b in rest: add(b)
    return ["hips"]+[b for b in out if b != "hips"]


def _region(b):
    if any(k in b for k in ("Thumb", "Index", "Middle", "Ring", "Little")): return "finger"
    if "Hand" in b: return "hand"
    if any(k in b for k in ("UpperArm", "LowerArm")): return "arm"
    if any(k in b for k in ("UpperLeg", "LowerLeg", "Foot")): return "leg"
    return "torso"
