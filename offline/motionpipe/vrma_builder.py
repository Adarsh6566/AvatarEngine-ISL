"""Build a real VRM Animation (.vrma) that drives AvatarSample_C.vrm from our
derived rest-relative deltas (Step 2E).

This is a FORMAT WRITER, not a re-mapper. It mirrors the avatar's own humanoid
rest hierarchy and writes, per bone/frame, the node LOCAL rotation
`animLocal = restLocal * delta`. three-vrm's loader normalizes this back with the
VRMA's own rest (= the avatar's rest), so retargeting onto AvatarSample_C is
identity and reproduces the pose our FK validated. No fromTo/IK/axis logic here.
"""
from __future__ import annotations

import json
import struct

from .target_rotations import extract_rest, qmul, qconj, qrot

_FLOAT, _GLB, _JSONC, _BINC = 5126, 0x46546C67, 0x4E4F534A, 0x004E4942


def _restlocal_rot(rest, b):
    hp = rest[b]["hparent"]
    return rest[b]["wrot"] if hp is None else qmul(qconj(rest[hp]["wrot"]), rest[b]["wrot"])


def _restlocal_tr(rest, b):
    hp = rest[b]["hparent"]
    if hp is None:
        return rest[b]["wpos"]
    return qrot(qconj(rest[hp]["wrot"]), rest[b]["wpos"] - rest[hp]["wpos"])


def build_vrma(rotations: dict, vrm_path=None) -> bytes:
    import numpy as np
    rest = extract_rest() if vrm_path is None else extract_rest(vrm_path)
    frames = rotations["frames"]
    fps = rotations["meta"]["fps"]
    bones = [b for b in frames[0]["rotations"] if b in rest]

    # collapsed humanoid node hierarchy (bone -> node index)
    idx = {b: i for i, b in enumerate(bones)}
    nodes = []
    for b in bones:
        rl = _restlocal_rot(rest, b); tr = _restlocal_tr(rest, b)
        nodes.append({"name": b,
                      "translation": [float(c) for c in tr],
                      "rotation": [float(c) for c in rl],
                      "children": [idx[c] for c in bones if rest[c]["hparent"] == b]})
    roots = [idx[b] for b in bones if rest[b]["hparent"] not in idx]

    times = [i / fps for i in range(len(frames))]
    bin_parts, accessors, bviews, off = [], [], [], [0]

    def add(data, count, kind, mm=None):
        bviews.append({"buffer": 0, "byteOffset": off[0], "byteLength": len(data)})
        a = {"bufferView": len(bviews) - 1, "componentType": _FLOAT, "count": count, "type": kind}
        if mm:
            a["min"], a["max"] = mm
        accessors.append(a); bin_parts.append(data); off[0] += len(data)
        pad = (-len(data)) % 4
        if pad:
            bin_parts.append(b"\x00" * pad); off[0] += pad
        return len(accessors) - 1

    t_acc = add(b"".join(struct.pack("<f", t) for t in times), len(times), "SCALAR",
                ([times[0]], [times[-1]]))
    samplers, channels = [], []
    for b in bones:
        rl = _restlocal_rot(rest, b)
        seq = [qmul(rl, np.array(f["rotations"][b])) for f in frames]  # animLocal per frame
        # skip constant (rest-only) bones to keep the file lean
        span = max(2 * float(np.arccos(min(1.0, abs(float(np.dot(seq[0], q)))))) for q in seq)
        if span < 0.02:
            continue
        data = b"".join(struct.pack("<ffff", *(q / np.linalg.norm(q))) for q in seq)
        r_acc = add(data, len(seq), "VEC4")
        samplers.append({"input": t_acc, "output": r_acc, "interpolation": "LINEAR"})
        channels.append({"sampler": len(samplers) - 1, "target": {"node": idx[b], "path": "rotation"}})

    human_bones = {b: {"node": idx[b]} for b in bones}
    gltf = {
        "asset": {"version": "2.0", "generator": "motionpipe.vrma_builder"},
        "extensionsUsed": ["VRMC_vrm_animation"],
        "scene": 0, "scenes": [{"nodes": roots}], "nodes": nodes,
        "animations": [{"name": "clip", "samplers": samplers, "channels": channels}],
        "accessors": accessors, "bufferViews": bviews, "buffers": [{"byteLength": off[0]}],
        "extensions": {"VRMC_vrm_animation": {"specVersion": "1.0",
                                              "humanoid": {"humanBones": human_bones}}},
    }
    j = json.dumps(gltf, separators=(",", ":")).encode(); j += b" " * ((-len(j)) % 4)
    blob = b"".join(bin_parts); blob += b"\x00" * ((-len(blob)) % 4)
    total = 12 + 8 + len(j) + 8 + len(blob)
    return (struct.pack("<III", _GLB, 2, total) + struct.pack("<II", len(j), _JSONC) + j
            + struct.pack("<II", len(blob), _BINC) + blob)
