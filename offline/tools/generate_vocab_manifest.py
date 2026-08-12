#!/usr/bin/env python3
"""Generate vocabulary/manifest fragments from public/animations/*.vrma (A).

Scans public/animations, prints JSON fragments for human to merge:
- manifest fragment for src/data/motion_manifest.json
- vocab fragment for backend/vocabulary.json

Usage:
  python offline/tools/generate_vocab_manifest.py --new-word namaste --gloss NAMASTE --vrma public/animations/namaste.vrma
  python offline/tools/generate_vocab_manifest.py --scan  # list orphans (vrma not in manifest)
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data/motion_manifest.json"
VOCAB = ROOT / "backend/vocabulary.json"
ANIM_DIR = ROOT / "public/animations"


def scan():
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    anims = {p.name for p in ANIM_DIR.glob("*.vrma")} if ANIM_DIR.exists() else set()
    manifest_assets = {v.get("assetPath", "").split("/")[-1] for v in manifest.values()}
    orphans = sorted(anims - manifest_assets)
    missing = sorted(manifest_assets - anims)
    print(f"animations on disk: {len(anims)}, in manifest: {len(manifest)}")
    if orphans:
        print("orphan .vrma not in manifest (need entry):")
        for o in orphans:
            print(f"  {o}")
    if missing:
        print("manifest asset missing on disk:")
        for m in missing:
            print(f"  {m}")
    if not orphans and not missing:
        print("manifest and animations in sync")


def fragment(word: str, gloss: str, vrma: str):
    # manifest fragment
    asset = vrma if vrma.startswith("/animations/") else f"/animations/{Path(vrma).name}"
    mf = {gloss: {"id": gloss, "motionId": f"word_{word.lower()}", "assetPath": asset, "duration": 1.8}}
    print("--- data/motion_manifest.json fragment (merge) ---")
    print(json.dumps(mf, indent=2))
    print("\n--- backend/vocabulary.json fragment (merge) ---")
    print(json.dumps({word.lower(): gloss}, indent=2))
    print(f"\nAfter merging, hot-reload: curl -X POST http://localhost:8000/admin/reload-vocab")
    print(f"Or restart: docker compose restart backend  (config.yaml backend.dictionary.path: {VOCAB})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", action="store_true", help="list orphans/missing")
    ap.add_argument("--new-word", help="english word (e.g. namaste)")
    ap.add_argument("--gloss", help="GLOSS id (e.g. NAMASTE)")
    ap.add_argument("--vrma", help="vrma path (e.g. public/animations/namaste.vrma)")
    args = ap.parse_args()
    if args.scan:
        scan()
    elif args.new_word and args.gloss and args.vrma:
        fragment(args.new_word, args.gloss, args.vrma)
    else:
        ap.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
