"""Stage 5 — Export (template-based).

RetargetedMotion -> a real VRM Animation (.vrma) + a ManifestFragment.

A .vrma needs a genuine humanoid REST POSE (non-zero hip height), or three-vrm
divides by a zero source-hip-height and the retargeted hips become NaN — the
avatar vanishes. Rather than invent a rest pose, this exporter reuses a real
Blender-authored VRMA as a TEMPLATE:

  REUSED from template (unchanged): asset, nodes (hierarchy + rest translations),
    scene, the VRMC_vrm_animation extension, and its humanBones mapping.
  REGENERATED from RetargetedMotion: buffers, bufferViews, accessors, and the
    animation (samplers + rotation channels), targeting the template's own node
    indices via humanBones.

The template has no meshes/skins/images, so its accessors are used only by the
old animation — replacing them wholesale is safe. Hips TRANSLATION is not written
(our motion is in-place / unit-torso normalized), so the template's rest hips
position is preserved intact.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Protocol, runtime_checkable

from .models import ClipMeta, ManifestFragment, MotionAsset, RetargetedMotion

_FLOAT, _GLB, _JSON, _BIN = 5126, 0x46546C67, 0x4E4F534A, 0x004E4942
_TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "hello_sign.vrma"


@runtime_checkable
class MotionExporter(Protocol):
    fmt: str

    def export(self, motion: RetargetedMotion, meta: ClipMeta, out_dir: str) -> MotionAsset: ...


class VRMAExporter:
    """Writes .vrma by grafting generated motion onto a template's rest skeleton."""

    fmt = "vrma"

    def __init__(self, template_path: str | Path = _TEMPLATE):
        self.template_path = Path(template_path)

    def export(self, motion: RetargetedMotion, meta: ClipMeta, out_dir: str) -> MotionAsset:
        blob = _graft(self.template_path.read_bytes(), motion.tracks, motion.fps)
        name = meta.clip_id.replace("/", "__") + ".vrma"
        anim_dir = Path(out_dir) / "animations"
        anim_dir.mkdir(parents=True, exist_ok=True)
        (anim_dir / name).write_bytes(blob)

        frag = ManifestFragment(
            id=meta.gloss, motionId=f"video_{meta.gloss.lower()}",
            assetPath=f"/animations/{name}", duration=motion.duration, dataset="video",
            provenance={"dataset": meta.dataset, "clip_id": meta.clip_id,
                        "signer_id": meta.signer_id, "source": "offline-pipeline",
                        "template": self.template_path.name},
        )
        return MotionAsset(vrma_path=str(anim_dir / name), fragment=frag)


# --- template graft --------------------------------------------------------


def _graft(template_bytes, tracks, fps):
    g = _load_glb_json(template_bytes)
    human_bones = g["extensions"]["VRMC_vrm_animation"]["humanoid"]["humanBones"]

    nframes = len(next(iter(tracks.values()))) if tracks else 0
    times = [i / fps for i in range(nframes)] if fps else [0.0]

    bin_parts, accessors, buffer_views, off = [], [], [], [0]

    def add(data, count, kind, minmax=None):
        buffer_views.append({"buffer": 0, "byteOffset": off[0], "byteLength": len(data)})
        acc = {"bufferView": len(buffer_views) - 1, "componentType": _FLOAT,
               "count": count, "type": kind}
        if minmax:
            acc["min"], acc["max"] = minmax
        accessors.append(acc)
        bin_parts.append(data)
        off[0] += len(data)
        pad = (-len(data)) % 4
        if pad:
            bin_parts.append(b"\x00" * pad)
            off[0] += pad
        return len(accessors) - 1

    t_acc = add(b"".join(struct.pack("<f", t) for t in times), len(times),
                "SCALAR", ([times[0]], [times[-1]]))

    samplers, channels = [], []
    for bone, rot in tracks.items():
        hb = human_bones.get(bone)
        if hb is None:            # bone not in template humanoid -> skip
            continue
        r_acc = add(b"".join(struct.pack("<ffff", *q) for q in rot), nframes, "VEC4")
        samplers.append({"input": t_acc, "output": r_acc, "interpolation": "LINEAR"})
        channels.append({"sampler": len(samplers) - 1,
                         "target": {"node": hb["node"], "path": "rotation"}})

    # Replace ONLY the animation data; keep nodes / rest pose / extension / humanBones.
    g["accessors"] = accessors
    g["bufferViews"] = buffer_views
    g["buffers"] = [{"byteLength": off[0]}]
    g["animations"] = [{"name": "clip", "samplers": samplers, "channels": channels}]
    return _pack_glb(g, b"".join(bin_parts))


def _load_glb_json(b):
    off, chunks = 12, {}
    while off < len(b):
        clen, ctyp = struct.unpack("<II", b[off:off + 8])
        off += 8
        chunks[ctyp] = b[off:off + clen]
        off += clen
    return json.loads(chunks[_JSON])


def _pack_glb(gltf, blob):
    j = json.dumps(gltf, separators=(",", ":")).encode()
    j += b" " * ((-len(j)) % 4)
    b = blob + b"\x00" * ((-len(blob)) % 4)
    total = 12 + 8 + len(j) + 8 + len(b)
    return (struct.pack("<III", _GLB, 2, total)
            + struct.pack("<II", len(j), _JSON) + j
            + struct.pack("<II", len(b), _BIN) + b)
