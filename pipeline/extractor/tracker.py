"""tracker — temporal left/right assignment for hands and wrists.

Fixes hand swap when hands overlap in fast ISL. Uses previous frame positions + handedness as tie-breaker.
All distances in view-pixels (YOLO) or normalized/world — caller passes same space for prev and cur.
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple, Optional

JointVal = Tuple[float, float, float, float] | None


def _dist(a: JointVal, b: JointVal) -> float:
    if a is None or b is None:
        return 999.0
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)


def assign_hands(
    detected: List[Dict],
    prev_l: JointVal,
    prev_r: JointVal,
    prev_lw: JointVal = None,
    prev_rw: JointVal = None,
) -> Dict[str, Dict | None]:
    """
    detected: list of {lm_list, handedness: "Left"/"Right", conf, centroid: JointVal, idx}
    Returns {"l": detected_or_None, "r": detected_or_None} assigned to l/r.
    """
    n = len(detected)
    if n == 0:
        return {"l": None, "r": None}
    if n == 1:
        d = detected[0]
        cat = d.get("handedness", "Unknown")
        is_left_label = cat.lower() == "left"
        # distance to prev
        dl = _dist(d["centroid"], prev_l) if prev_l is not None else 999
        dr = _dist(d["centroid"], prev_r) if prev_r is not None else 999
        # also check wrist proximity if available
        if prev_lw is not None and prev_rw is not None:
            dlw = _dist(d["centroid"], prev_lw)
            drw = _dist(d["centroid"], prev_rw)
            dl = min(dl, dlw)
            dr = min(dr, drw)
        # if both prev are None (first frame), trust label
        if prev_l is None and prev_r is None:
            return {"l": d if is_left_label else None, "r": d if not is_left_label else None}
        # if label confidence high (>0.7) and distances are close, trust label
        conf = d.get("conf", 0.5)
        # choose closest, but with small penalty for contradicting label
        penalty_l = 0.0 if is_left_label else 0.04
        penalty_r = 0.0 if not is_left_label else 0.04
        # if distances far apart, pick closest
        # if one distance is much smaller (>0.05 diff), pick it regardless of label
        if abs(dl - dr) > 0.03:
            if dl < dr:
                return {"l": d, "r": None}
            else:
                return {"l": None, "r": d}
        # close distances — use label with penalty
        if dl + penalty_l < dr + penalty_r:
            return {"l": d, "r": None}
        else:
            return {"l": None, "r": d}

    # n == 2
    # need to handle case where prev are None (first frame)
    if prev_l is None and prev_r is None:
        # assign by label
        out = {"l": None, "r": None}
        for d in detected:
            is_left = d.get("handedness", "").lower() == "left"
            if is_left and out["l"] is None:
                out["l"] = d
            elif not is_left and out["r"] is None:
                out["r"] = d
            else:
                # both same label (both Left), assign by position (leftmost x to r? Actually person's left is image right)
                # fallback to x position
                pass
        # if still unassigned (both same label), assign by x
        if out["l"] is None or out["r"] is None:
            # sort by x centroid
            sorted_d = sorted(detected, key=lambda x: x["centroid"][0] if x["centroid"] else 0)
            # for person facing camera, left hand (person's left) appears on image right (larger x)
            # but we don't know orientation; just assign leftmost to r and rightmost to l if both labeled same
            # This is heuristic; better to use distance to prev wrists if available
            if out["l"] is None and out["r"] is None:
                # both same label, use x
                # if we have prev wrists, use them
                if prev_lw is not None and prev_rw is not None:
                    # assign by closest to wrists
                    d0, d1 = detected[0], detected[1]
                    c00 = _dist(d0["centroid"], prev_lw) + _dist(d1["centroid"], prev_rw)
                    c01 = _dist(d0["centroid"], prev_rw) + _dist(d1["centroid"], prev_lw)
                    if c00 <= c01:
                        return {"l": d0, "r": d1}
                    else:
                        return {"l": d1, "r": d0}
                # fallback: assume left hand is rightmost in image (person facing camera)
                out["l"] = sorted_d[1]
                out["r"] = sorted_d[0]
        return out

    # both prev exist, try both permutations
    d0, d1 = detected[0], detected[1]
    # cost for assignment A: d0->l, d1->r
    def cost(d, prev, is_left, target_is_left):
        base = _dist(d["centroid"], prev)
        # small penalty if handedness mismatches target
        label_is_left = d.get("handedness","").lower()=="left"
        penalty = 0.0 if label_is_left == target_is_left else 0.05
        # wrist proximity bonus
        if target_is_left and prev_lw is not None:
            base = min(base, _dist(d["centroid"], prev_lw))
        if not target_is_left and prev_rw is not None:
            base = min(base, _dist(d["centroid"], prev_rw))
        return base + penalty

    cost_a = cost(d0, prev_l, d0.get("handedness","").lower()=="left", True) + cost(d1, prev_r, d1.get("handedness","").lower()=="left", False)
    cost_b = cost(d0, prev_r, d0.get("handedness","").lower()=="left", False) + cost(d1, prev_l, d1.get("handedness","").lower()=="left", True)
    if cost_a <= cost_b:
        return {"l": d0, "r": d1}
    else:
        return {"l": d1, "r": d0}


def maybe_swap_wrists(
    cur_l: JointVal,
    cur_r: JointVal,
    prev_l: JointVal,
    prev_r: JointVal,
    thresh: float = 0.08,
) -> tuple[JointVal, JointVal, bool]:
    """Detect YOLO left/right wrist swap: if cross-distance smaller, swap. Returns (l,r,swapped)."""
    if cur_l is None or cur_r is None or prev_l is None or prev_r is None:
        return cur_l, cur_r, False
    d_ok = _dist(cur_l, prev_l) + _dist(cur_r, prev_r)
    d_swap = _dist(cur_l, prev_r) + _dist(cur_r, prev_l)
    # if swap distance is significantly smaller, we likely have a swap
    if d_swap + thresh < d_ok:
        return cur_r, cur_l, True
    return cur_l, cur_r, False
