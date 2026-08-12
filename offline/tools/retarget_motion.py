"""CLI: NormalizedMotion JSON -> RetargetedMotion JSON (VRM humanoid).

    python offline/tools/retarget_motion.py --clip MVI_0029

Reads output/normalized/, writes output/retargeted/. No VRMA export / runtime.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

OFFLINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OFFLINE))

from motionpipe import io  # noqa: E402
from motionpipe.models import ClipMeta, NormalizedMotion, SkeletalBone, SkeletalFrame  # noqa: E402
from motionpipe.retarget import VRMHumanoidProfile, retarget  # noqa: E402

NORM_DIR = OFFLINE / "output" / "normalized"
OUT_DIR = OFFLINE / "output" / "retargeted"


def _tup(v):
    return None if v is None else tuple(v)


def rehydrate(d) -> NormalizedMotion:
    frames = [
        SkeletalFrame(f["t"], [SkeletalBone(b["name"], b["parent"], tuple(b["local_position"]),
                                            _tup(b["local_rotation"]), b["confidence"])
                               for b in f["bones"]])
        for f in d["frames"]
    ]
    return NormalizedMotion(d["skeleton"], d["fps"], d["duration"], frames,
                            ClipMeta(**d["meta"]), d.get("scale_factor", 1.0),
                            d.get("trimmed_frames", 0))


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="Retarget canonical motion to a rig.")
    ap.add_argument("--clip", help="match a file in output/normalized/ by substring")
    ap.add_argument("--input")
    args = ap.parse_args(argv[1:])

    path = args.input or next(
        (p for p in glob.glob(str(NORM_DIR / "*.json"))
         if not args.clip or args.clip.lower() in Path(p).name.lower()), None)
    if not path:
        print("No normalized file matched. Run normalize_motion.py first.")
        return 1

    profile = VRMHumanoidProfile()
    motion = rehydrate(json.load(open(path)))
    rm = retarget(motion, profile)
    out = OUT_DIR / Path(path).name
    io.write(rm, out)

    bmap = profile.bone_map()
    mapped = sorted(rm.tracks)
    unmapped_target = sorted(profile.target_bones() - set(mapped))
    unmapped_source = sorted(set(b.name for b in motion.frames[0].bones) - set(bmap))

    print(f"rig            : {rm.target_rig}   frames={len(motion.frames)} fps={rm.fps:.1f}")
    print(f"mapped bones   : {len(mapped)} -> {mapped}")
    print(f"unmapped source: {unmapped_source or 'none'}")
    print(f"avg confidence : {rm.confidence:.3f}")
    for b in unmapped_target:
        print(f"  ⚠ target bone '{b}' has no canonical source (rig will use its rest pose)")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
