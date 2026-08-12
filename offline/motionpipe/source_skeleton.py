"""SourceSkeletonSequence — schema source_skeleton.v1.

A humanoid SOURCE skeleton (body + both hands with per-finger chains) driven
purely by the landmarks in a HumanMotionSequence. POSITIONS ONLY — no rotations,
no VRM mapping, no IK, no calibration. Coordinates stay in the SAME MediaPipe
image-normalized space as the source (X right, Y down, MediaPipe Z); a later
stage owns any conversion. This is a SOURCE skeleton, not the VRM skeleton.

Landmark correspondence is data (JOINT_SPECS), not scattered logic. Body/hand
landmarks are addressed by MediaPipe INDEX into the source frame's group lists.
"""
from __future__ import annotations

SCHEMA_VERSION = "source_skeleton.v1"
COORDINATE_SPACE = "mediapipe_image_normalized (X right, Y down, MP depth Z)"

# Resolver forms: ("b",i)=body[i]; ("mid_b",i,j)=midpoint of body i,j;
# ("h",side,i)=<side>_hand[i]; ("midj",a,b)=midpoint of already-computed joints.
# (name, parent, resolver). Body derived joints are ordered so their inputs exist.
BODY_SPECS = [
    ("hips",         None,          ("mid_b", 23, 24)),   # pelvis center
    ("chest",        "spine",       ("mid_b", 11, 12)),   # shoulder center
    ("head",         "neck",        ("mid_b", 7, 8)),     # ear center
    ("spine",        "hips",        ("midj", "hips", "chest")),
    ("neck",         "chest",       ("midj", "chest", "head")),
    ("leftShoulder", "chest",       ("b", 11)),
    ("leftElbow",    "leftShoulder",("b", 13)),
    ("leftWrist",    "leftElbow",   ("b", 15)),
    ("rightShoulder","chest",       ("b", 12)),
    ("rightElbow",   "rightShoulder",("b", 14)),
    ("rightWrist",   "rightElbow",  ("b", 16)),
    ("leftHip",      "hips",        ("b", 23)),
    ("leftKnee",     "leftHip",     ("b", 25)),
    ("leftAnkle",    "leftKnee",    ("b", 27)),
    ("rightHip",     "hips",        ("b", 24)),
    ("rightKnee",    "rightHip",    ("b", 26)),
    ("rightAnkle",   "rightKnee",   ("b", 28)),
]

# MediaPipe hand topology: WRIST=0; then 4 joints per finger.
_FINGERS = {
    "Thumb":  [("CMC", 1), ("MCP", 2), ("IP", 3), ("TIP", 4)],
    "Index":  [("MCP", 5), ("PIP", 6), ("DIP", 7), ("TIP", 8)],
    "Middle": [("MCP", 9), ("PIP", 10), ("DIP", 11), ("TIP", 12)],
    "Ring":   [("MCP", 13), ("PIP", 14), ("DIP", 15), ("TIP", 16)],
    "Pinky":  [("MCP", 17), ("PIP", 18), ("DIP", 19), ("TIP", 20)],
}


def _hand_specs(side):
    wrist = f"{side}HandWrist"
    specs = [(wrist, f"{side}Wrist", ("h", side, 0))]
    for finger, joints in _FINGERS.items():
        prev = wrist
        for jn, idx in joints:
            name = f"{side}{finger}{jn}"
            specs.append((name, prev, ("h", side, idx)))
            prev = name
    return specs


JOINT_SPECS = BODY_SPECS + _hand_specs("left") + _hand_specs("right")
HIERARCHY = [(parent, name) for name, parent, _ in JOINT_SPECS if parent]


def _mp(lm):
    return [lm["x"], lm["y"], lm["z"], lm["confidence"]]


def _mid(a, b):
    if a is None or b is None:
        return None
    return [(a[0]+b[0])/2, (a[1]+b[1])/2, (a[2]+b[2])/2, min(a[3], b[3])]


def _resolve(res, body, lh, rh, J):
    kind = res[0]
    if kind == "b":
        return _mp(body[res[1]])
    if kind == "mid_b":
        return _mid(_mp(body[res[1]]), _mp(body[res[2]]))
    if kind == "h":
        lst = lh if res[1] == "left" else rh
        return _mp(lst[res[2]]) if lst else None      # hand absent -> missing
    if kind == "midj":
        return _mid(J.get(res[1]), J.get(res[2]))
    return None


def _describe(res):
    return {"b": f"body[{res[1] if len(res)>1 else ''}]", "mid_b": f"mid(body[{res[1:]}])",
            "h": f"{res[1]}_hand[{res[2]}]" if len(res) > 2 else "",
            "midj": f"mid({res[1:]})"}.get(res[0], str(res))


def from_human_motion(hm: dict) -> dict:
    """HumanMotionSequence dict -> SourceSkeletonSequence dict (positions only)."""
    m = hm["meta"]
    frames = []
    for f in hm["frames"]:
        body, lh, rh = f["body"], f["left_hand"], f["right_hand"]
        J = {}
        for name, _parent, res in JOINT_SPECS:
            J[name] = _resolve(res, body, lh, rh, J)
        frames.append({"index": f["index"], "timestamp": f["timestamp"], "joints": J})

    meta = {
        "schema": SCHEMA_VERSION,
        "source_video": m["source_video"], "gloss": m["gloss"],
        "estimator": m["estimator"], "coordinate_space": COORDINATE_SPACE,
        "fps": m["fps"], "frame_count": len(frames),
        "duration": m["duration"],
        "joints": [{"name": n, "parent": p} for n, p, _ in JOINT_SPECS],
        "hierarchy": HIERARCHY,
        "landmark_map": {n: _describe(r) for n, _p, r in JOINT_SPECS},
        "joint_count": len(JOINT_SPECS),
    }
    return {"meta": meta, "frames": frames}
