"""Target skeleton, source->target correspondence, and calibration CONTRACT.

Schemas: target_skeleton.v1 / skeleton_mapping.v1 / calibration.v1.

Geometry + correspondence ONLY — no rotations, no IK, no VRM animation, no VRMA.
The target skeleton is derived from the ACTUAL avatar (public/models/AvatarSample_C.vrm,
VRM 1.0). Source names come from source_skeleton.v1. A later stage (2C) owns the
per-frame mapping and the coordinate conversion; nothing is applied to the source here.
"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Protocol, runtime_checkable

VRM_ASSET = Path(__file__).resolve().parents[2] / "public" / "models" / "AvatarSample_C.vrm"

TARGET_COORD = {"space": "vrm1", "x": "right", "y": "up", "z": "forward",
                "handedness": "right", "metric": True, "unit": "meter"}
SOURCE_COORD = {"space": "mediapipe_image_normalized", "x": "right", "y": "down",
                "z": "mp_depth", "metric": False}

# --- source(head joint) -> target(bone) correspondence, as DATA ------------
# target bone : source joint whose position defines that bone's HEAD. None = the
# target bone has no source equivalent (kept at rest).
_BODY_MAP = {
    "hips": "hips", "spine": "spine", "chest": "chest", "upperChest": None,
    "neck": "neck", "head": "head",
    "leftShoulder": None, "leftUpperArm": "leftShoulder", "leftLowerArm": "leftElbow",
    "leftHand": "leftHandWrist",
    "rightShoulder": None, "rightUpperArm": "rightShoulder", "rightLowerArm": "rightElbow",
    "rightHand": "rightHandWrist",
    "leftUpperLeg": "leftHip", "leftLowerLeg": "leftKnee", "leftFoot": "leftAnkle",
    "leftToes": None, "leftEye": None,
    "rightUpperLeg": "rightHip", "rightLowerLeg": "rightKnee", "rightFoot": "rightAnkle",
    "rightToes": None, "rightEye": None,
}
# VRM finger bone -> source finger joint. NOTE: VRM "Little" == source "Pinky".
# Thumb: Metacarpal/Proximal/Distal <- CMC/MCP/IP. Others: Prox/Inter/Distal <- MCP/PIP/DIP.
_FINGER_MAP = {
    "Thumb":  [("Metacarpal", "CMC"), ("Proximal", "MCP"), ("Distal", "IP")],
    "Index":  [("Proximal", "MCP"), ("Intermediate", "PIP"), ("Distal", "DIP")],
    "Middle": [("Proximal", "MCP"), ("Intermediate", "PIP"), ("Distal", "DIP")],
    "Ring":   [("Proximal", "MCP"), ("Intermediate", "PIP"), ("Distal", "DIP")],
    "Little": [("Proximal", "MCP"), ("Intermediate", "PIP"), ("Distal", "DIP")],
}


def source_to_target() -> dict:
    """Full target_bone -> source_joint map (None = unmapped target)."""
    m = dict(_BODY_MAP)
    for side in ("left", "right"):
        for tfinger, joints in _FINGER_MAP.items():
            sfinger = "Pinky" if tfinger == "Little" else tfinger
            for tj, sj in joints:
                m[f"{side}{tfinger}{tj}"] = f"{side}{sfinger}{sj}"
    return m


# --- extract the real target skeleton from the VRM -------------------------


def extract_target(vrm_path: Path = VRM_ASSET) -> dict:
    b = vrm_path.read_bytes()
    o, ch = 12, {}
    while o < len(b):
        ln, ty = struct.unpack("<II", b[o:o + 8]); o += 8; ch[ty] = b[o:o + ln]; o += ln
    g = json.loads(ch[0x4E4F534A]); N = g["nodes"]
    hb = g["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]
    node = {k: (v["node"] if isinstance(v, dict) else v) for k, v in hb.items()}
    bone_of = {n: k for k, n in node.items()}
    par = {}
    for i, nd in enumerate(N):
        for c in nd.get("children", []):
            par[c] = i

    def wpos(i):
        p, j = [0.0, 0.0, 0.0], i
        chain = []
        while j is not None:
            chain.append(j); j = par.get(j)
        for k in reversed(chain):
            t = N[k].get("translation", [0, 0, 0]); p = [p[m] + t[m] for m in range(3)]
        return p

    def humanoid_parent(bone):
        j = par.get(node[bone])
        while j is not None:
            if j in bone_of:
                return bone_of[j]
            j = par.get(j)
        return None

    bones = []
    for bone in sorted(node):
        hp = humanoid_parent(bone)
        rw = wpos(node[bone])
        blen = round(math.dist(rw, wpos(par.get(node[bone], node[bone]))), 4) if hp else None
        bones.append({"name": bone, "parent": hp,
                      "rest_world": [round(c, 4) for c in rw],
                      "bone_length_from_parent": blen,
                      "is_finger": any(f in bone for f in ("Thumb", "Index", "Middle", "Ring", "Little"))})
    return {"schema": "target_skeleton.v1", "source_asset": vrm_path.name,
            "coordinate_space": TARGET_COORD, "bone_count": len(bones), "bones": bones,
            "hierarchy": [[b["parent"], b["name"]] for b in bones if b["parent"]]}


# --- future mapper contract (NOT implemented here — belongs to Step 2C) -----


@runtime_checkable
class SkeletonMapper(Protocol):
    """Contract for the future per-frame mapper. Given a source skeleton frame,
    the target skeleton definition, and a calibration, it will produce target
    joint poses. Step 2C implements it (possibly SPARK-style) behind THIS boundary.
    """

    name: str

    def map_frame(self, source_frame: dict, target: dict, calibration: dict) -> dict:
        """SourceSkeletonFrame -> target joint poses. NOT implemented in 2B."""
        ...
