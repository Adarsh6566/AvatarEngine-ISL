"""CLI: RetargetedMotion JSON -> .vrma + manifest fragment.

    python offline/tools/export_motion.py --clip MVI_0029

Writes .vrma to output/animations/ and a merge-ready manifest fragment to
output/manifests/. Runtime is NOT touched.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from dataclasses import asdict
from pathlib import Path

OFFLINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OFFLINE))

from motionpipe.export_vrma import VRMAExporter  # noqa: E402
from motionpipe.models import ClipMeta, RetargetedMotion  # noqa: E402

RETARGETED_DIR = OFFLINE / "output" / "retargeted"
OUT = OFFLINE / "output"


def rehydrate(d) -> RetargetedMotion:
    tracks = {k: [tuple(q) for q in v] for k, v in d["tracks"].items()}
    hips = [tuple(v) for v in d.get("hips_translation") or []]
    return RetargetedMotion(d["target_rig"], d["duration"], tracks, d["fps"], hips,
                            ClipMeta(**d["meta"]), d.get("confidence", 0.0))


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="Export retargeted motion to .vrma.")
    ap.add_argument("--clip")
    ap.add_argument("--input")
    args = ap.parse_args(argv[1:])

    path = args.input or next(
        (p for p in glob.glob(str(RETARGETED_DIR / "*.json"))
         if not args.clip or args.clip.lower() in Path(p).name.lower()), None)
    if not path:
        print("No retargeted file matched. Run retarget_motion.py first.")
        return 1

    motion = rehydrate(json.load(open(path)))
    asset = VRMAExporter().export(motion, motion.meta, str(OUT))

    # Merge-ready manifest fragment: keyed by gloss, matching motion_manifest.json.
    f = asset.fragment
    man_dir = OUT / "manifests"
    man_dir.mkdir(parents=True, exist_ok=True)
    frag_path = man_dir / (Path(asset.vrma_path).stem + ".json")
    entry = {f.id: {"motionId": f.motionId, "assetPath": f.assetPath,
                    "duration": f.duration, "dataset": f.dataset, "provenance": f.provenance}}
    frag_path.write_text(json.dumps(entry, indent=2))

    print(f"exported : {Path(asset.vrma_path).name}")
    print(f"duration : {motion.duration:.2f}s   fps: {motion.fps:.1f}")
    print(f"tracks   : {len(motion.tracks)} bone rotation tracks (+hips translation)")
    print(f"vrma     -> {asset.vrma_path}")
    print(f"manifest -> {frag_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
