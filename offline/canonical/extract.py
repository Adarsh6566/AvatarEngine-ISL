"""Extract every take of every sign to the view-space cache the builder reads.

    python -m offline.canonical.extract --source <recordings-dir> --cache <takes-dir>

This is stage 1-3 of the canonical pipeline (docs/CANONICAL_MOTION.md): pose
extraction, normalisation to view space, per-joint smoothing. It is the step
`build.py` assumes has already run, and it deliberately reuses `pipeline/`'s
extractor rather than reimplementing it, so takes captured for the dashboard
and takes captured for a canonical are the same numbers.

Source layout is the recording set as delivered — one directory per sign,
named `<number>. <words>`, holding one .MOV per take:

    45. we/MVI_0017.MOV        ->  <cache>/we/MVI_0017.json
    46. you (plural)/...       ->  <cache>/you_plural/...

Face capture is turned OFF here. `write_stream` keeps only joints, so the
blendshapes would be computed and then discarded — and the face landmarker
runs a second model over an upscaled crop of every frame, which is most of the
extraction cost. Nothing downstream of this script can tell the difference.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

VIDEO_SUFFIXES = {".mov", ".mp4", ".m4v", ".avi", ".mkv"}


def slug(folder_name: str) -> str:
    """`45. you (plural)` -> `you_plural`.

    The leading index is ordering within the delivered set, not part of the
    sign's identity, so it is dropped; everything else collapses to the
    lowercase underscore form the rest of the pipeline uses for filenames.
    """
    name = re.sub(r"^\s*\d+\s*[.)-]\s*", "", folder_name)
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def extract_one(args: tuple[str, str, str]) -> dict:
    """Extract one take. Runs in a worker process, so it takes plain strings."""
    video, out_path, sign = args
    src, dst = Path(video), Path(out_path)
    if dst.exists():
        return {"take": src.stem, "sign": sign, "skipped": True}

    # Imported inside the worker: each process builds its own landmarkers, and
    # importing at module scope would pay that cost in the parent too.
    from pipeline.extractor import face as face_capture
    from pipeline.extractor.mediapipe_extractor import MediaPipeExtractor
    from pipeline.extractor.normalize import to_view_space
    from pipeline.extractor.smooth import smooth_stream

    # See module docstring: the blendshapes would be discarded downstream.
    face_capture._UNAVAILABLE = "off for take extraction"

    started = time.perf_counter()
    try:
        stream = MediaPipeExtractor().extract(src, space="world")
        view = smooth_stream(to_view_space(stream))
    except Exception as e:
        return {"take": src.stem, "sign": sign, "error": f"{type(e).__name__}: {e}"}

    meta = view.meta.model_dump(by_alias=True)
    meta["source_video"] = src.name
    meta["gloss"] = sign.upper()

    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "frames": [f.model_dump() for f in view.frames]}, fh)

    return {
        "take": src.stem,
        "sign": sign,
        "frames": meta["frameCount"],
        "fps": meta["fps"],
        "seconds": round(time.perf_counter() - started, 1),
    }


def plan(source: Path, cache: Path, signs: list[str] | None) -> list[tuple[str, str, str]]:
    jobs: list[tuple[str, str, str]] = []
    for folder in sorted(p for p in source.iterdir() if p.is_dir()):
        sign = slug(folder.name)
        if signs and sign not in signs:
            continue
        for video in sorted(folder.iterdir()):
            if video.suffix.lower() in VIDEO_SUFFIXES:
                jobs.append((str(video), str(cache / sign / f"{video.stem}.json"), sign))
    return jobs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, type=Path, help="dir of '<n>. <sign>/<take>.MOV'")
    ap.add_argument("--cache", required=True, type=Path, help="dir to write <sign>/<take>.json")
    ap.add_argument("--signs", nargs="*", default=None, help="slugs to limit the run to")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    jobs = plan(args.source, args.cache, args.signs)
    if not jobs:
        print(f"no videos found under {args.source}")
        sys.exit(1)

    by_sign: dict[str, int] = {}
    for _, _, sign in jobs:
        by_sign[sign] = by_sign.get(sign, 0) + 1
    print(f"{len(jobs)} takes across {len(by_sign)} signs on {args.workers} workers")
    for sign, n in by_sign.items():
        print(f"  {sign:16s} {n} takes")

    started = time.perf_counter()
    done = failed = skipped = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for r in pool.map(extract_one, jobs):
            if r.get("skipped"):
                skipped += 1
                continue
            if "error" in r:
                failed += 1
                print(f"  FAILED {r['sign']}/{r['take']}: {r['error']}", flush=True)
                continue
            done += 1
            print(
                f"  [{done + failed + skipped}/{len(jobs)}] {r['sign']}/{r['take']}"
                f"  {r['frames']} frames @ {r['fps']:.0f}fps  {r['seconds']}s",
                flush=True,
            )

    elapsed = time.perf_counter() - started
    print(f"\n{done} extracted, {skipped} already cached, {failed} failed in {elapsed:.0f}s")
    print(f"cache -> {args.cache.resolve()}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
