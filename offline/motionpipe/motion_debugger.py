"""READ-ONLY motion diagnostics. Loads existing artifacts + the real
AvatarSample_C rest skeleton and computes per-frame per-bone comparison numbers.
Does NOT modify or re-run any mapping. FK reuses the frozen target_rotations math.
"""
from __future__ import annotations
import glob, json, math
from pathlib import Path
import numpy as np

from .target_rotations import extract_rest, qmul, qconj, qrot, IDENT, _DC, _order

OFF = Path(__file__).resolve().parents[1]
OUT = OFF / "output"


def load():
    src = json.load(open(sorted(glob.glob(str(OUT / "source_skeleton" / "*.json")))[0]))
    tm = json.load(open(OUT / "target_motion" / "target_motion.v1.json"))
    rot = json.load(open(OUT / "target_motion" / "target_rotations_temporal.v1.json"))
    rest = extract_rest()
    order = [b for b in _order(rest) if b in rest]
    return src, tm, rot, rest, order


def fk_frame(rest, order, rotframe, hips_anchor):
    fp, fr = {}, {}
    for b in order:
        hp = rest[b]["hparent"]; d = np.array(rotframe[b])
        rl = qmul(qconj(rest[hp]["wrot"] if hp else IDENT), rest[b]["wrot"])
        if hp is None:
            fr[b] = qmul(rl, d); fp[b] = np.array(hips_anchor)
        else:
            fr[b] = qmul(fr[hp], qmul(rl, d))
            off = qrot(qconj(rest[hp]["wrot"]), rest[b]["wpos"] - rest[hp]["wpos"])
            fp[b] = fp[hp] + qrot(fr[hp], off)
    return fp


def _ang(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-9 or nb < 1e-9:
        return None
    return math.degrees(math.acos(np.clip(np.dot(a, b) / (na * nb), -1, 1)))


def _region(b):
    if any(k in b for k in ("Thumb", "Index", "Middle", "Ring", "Little")):
        return "finger"
    if "Hand" in b:
        return "hand"
    if any(k in b for k in ("UpperArm", "LowerArm", "Shoulder")):
        return "arm"
    if any(k in b for k in ("UpperLeg", "LowerLeg", "Foot")):
        return "leg"
    return "torso"


def analyze(src, tm, rot, rest, order):
    """Return (per_frame_fk, report). report has directional/length/discontinuity stats."""
    n = len(tm["frames"])
    fks = []
    dir_err = {}      # region -> list of (angle, frame, bone)
    length = {}       # bone -> (target_len_median, rest_len, ratio)
    disc = {}         # bone -> (max frame-to-frame quat angle, frame)
    src_disc, tgt_disc = {}, {}   # source-space and target-space dir discontinuities

    for fi in range(n):
        Tj = {b: (np.array(j["position"]) if j["position"] else None)
              for b, j in tm["frames"][fi]["joints"].items()}
        R = rot["frames"][fi]["rotations"]
        anchor = Tj.get("hips", rest["hips"]["wpos"])
        fp = fk_frame(rest, order, R, anchor)
        fks.append(fp)
        for b in order:
            c = _DC.get(b)
            if not c:
                continue
            tb, tc = Tj.get(b), Tj.get(c)
            fb, fc = fp.get(b), fp.get(c if c in fp else None)
            if tb is not None and tc is not None and fb is not None and fc is not None:
                a = _ang(tc - tb, fc - fb)
                if a is not None:
                    dir_err.setdefault(_region(b), []).append((a, fi, b))
    # length ratios (median target vs avatar rest)
    for b in order:
        c = _DC.get(b)
        if not c or c not in rest:
            continue
        tls = []
        for fi in range(n):
            Tj = tm["frames"][fi]["joints"]
            if Tj.get(b, {}).get("position") and Tj.get(c, {}).get("position"):
                tls.append(np.linalg.norm(np.array(Tj[c]["position"]) - np.array(Tj[b]["position"])))
        if tls:
            rl = float(np.linalg.norm(rest[c]["wpos"] - rest[b]["wpos"]))
            tlm = float(np.median(tls))
            length[b] = (round(tlm, 4), round(rl, 4), round(tlm / rl, 3) if rl > 1e-6 else None)
    # rotation frame-to-frame discontinuities (target rotations, raw)
    for b in rot["frames"][0]["rotations"]:
        mx, mxf = 0.0, 0
        for fi in range(1, n):
            q0 = np.array(rot["frames"][fi - 1]["rotations"][b])
            q1 = np.array(rot["frames"][fi]["rotations"][b])
            ang = 2 * math.degrees(math.acos(min(1.0, abs(float(np.dot(q0, q1))))))
            if ang > mx:
                mx, mxf = ang, fi
        disc[b] = (round(mx, 1), mxf)
    # SOURCE-space discontinuity over the SOURCE hierarchy (source joint names).
    from .source_skeleton import HIERARCHY as S_HIER
    for parent, child in S_HIER:
        prev = None; mx, mxf = 0.0, 0
        for fi in range(len(src["frames"])):
            J = src["frames"][fi]["joints"]
            pb, pc = J.get(parent), J.get(child)
            d = None if (pb is None or pc is None) else (np.array(pc[:3]) - np.array(pb[:3]))
            if d is not None and prev is not None:
                aa = _ang(prev, d)
                if aa and aa > mx:
                    mx, mxf = aa, fi
            prev = d if d is not None else prev
        src_disc[child] = (round(mx, 1), mxf)
    # TARGET-space discontinuity over VRM bones (target_motion positions).
    for b in order:
        c = _DC.get(b)
        if not c:
            continue
        prev = None; mx, mxf = 0.0, 0
        for fi in range(len(tm["frames"])):
            J = tm["frames"][fi]["joints"]
            pb = J.get(b, {}).get("position"); pc = J.get(c, {}).get("position")
            d = None if (pb is None or pc is None) else (np.array(pc) - np.array(pb))
            if d is not None and prev is not None:
                aa = _ang(prev, d)
                if aa and aa > mx:
                    mx, mxf = aa, fi
            prev = d if d is not None else prev
        tgt_disc[b] = (round(mx, 1), mxf)

    def worst(region):
        items = dir_err.get(region, [])
        return max(items, key=lambda x: x[0]) if items else (0, -1, None)

    report = {
        "frames": n, "fps": tm["meta"]["fps"],
        "dir_err_by_region": {r: {"mean": round(float(np.mean([a for a, _, _ in v])), 2),
                                  "max": round(max(v)[0], 2), "worst_frame": max(v)[1],
                                  "worst_bone": max(v)[2]} for r, v in dir_err.items()},
        "worst": {r: worst(r) for r in ("torso", "arm", "hand", "finger", "leg")},
        "length_ratio": length,
        "rotation_discontinuity_top": sorted(disc.items(), key=lambda kv: -kv[1][0])[:8],
        "source_dir_disc_top": sorted(src_disc.items(), key=lambda kv: -kv[1][0])[:6],
        "target_dir_disc_top": sorted(tgt_disc.items(), key=lambda kv: -kv[1][0])[:6],
    }
    return fks, report
