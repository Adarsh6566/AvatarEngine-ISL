"""CLI: derived rotations -> real .vrma for AvatarSample_C.vrm + structural validation.

    python offline/tools/build_vrma.py [--rotations <file>] [--out <file>]
Default input = target_rotations_temporal.v1.json (2E). Writes offline/output/vrma/.
"""
from __future__ import annotations
import argparse, json, math, struct, sys
from pathlib import Path

OFF = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(OFF))
from motionpipe.vrma_builder import build_vrma  # noqa: E402

TMOT = OFF / "output" / "target_motion"
OUT = OFF / "output" / "vrma"


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--rotations", default=str(TMOT / "target_rotations_temporal.v1.json"))
    ap.add_argument("--out", default=str(OUT / "hello_isl.vrma"))
    a = ap.parse_args(argv[1:])
    rot = json.load(open(a.rotations))
    blob = build_vrma(rot)
    OUT.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_bytes(blob)

    # structural validation
    magic, ver, total = struct.unpack("<III", blob[:12])
    jlen, jtyp = struct.unpack("<II", blob[12:20])
    g = json.loads(blob[20:20 + jlen])
    anim = g["animations"][0]
    hb = g["extensions"]["VRMC_vrm_animation"]["humanoid"]["humanBones"]
    # NaN + quat-norm scan on rotation accessors
    binoff = 20 + jlen + 8
    bn = blob[binoff:]
    bad = 0; norms = []
    for c in anim["channels"]:
        acc = g["accessors"][anim["samplers"][c["sampler"]]["output"]]
        bv = g["bufferViews"][acc["bufferView"]]
        vals = struct.unpack_from("<%df" % (acc["count"] * 4), bn, bv.get("byteOffset", 0))
        for k in range(acc["count"]):
            q = vals[k * 4:k * 4 + 4]
            if any(not math.isfinite(x) for x in q):
                bad += 1
            norms.append(math.sqrt(sum(x * x for x in q)))
    fingers = [b for b in hb if any(f in b for f in ("Thumb", "Index", "Middle", "Ring", "Little"))]
    animated = {c["target"]["node"] for c in anim["channels"]}
    anim_fingers = [b for b in fingers if hb[b]["node"] in animated]
    print(f"GLB magic={magic==_G} version={ver} size_ok={len(blob)==total} bytes={len(blob)}")
    print(f"nodes={len(g['nodes'])} humanBones={len(hb)} animated_channels={len(anim['channels'])}")
    print(f"VRMC_vrm_animation={'VRMC_vrm_animation' in g.get('extensionsUsed',[])} specVer="
          f"{g['extensions']['VRMC_vrm_animation']['specVersion']}")
    print(f"frames={rot['meta']['frame_count']} fps={rot['meta']['fps']} "
          f"duration~{rot['meta']['frame_count']/rot['meta']['fps']:.2f}s")
    print(f"animated finger bones={len(anim_fingers)}/30  (both hands)")
    print(f"rotation values: NaN/Inf={bad}  quat-norm[min={min(norms):.4f} max={max(norms):.4f}]")
    print(f"-> {a.out}")
    return 0


_G = 0x46546C67
if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
