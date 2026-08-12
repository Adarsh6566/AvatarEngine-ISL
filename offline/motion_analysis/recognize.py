"""CLI: python -m offline.motion_analysis.recognize --query query.npz --database offline/output/sign_database (Phase 5)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .graph import from_npz, SkeletonGraphSequence
from .eemgm import SignDatabase, SignEntry, eemgm


def build_db(db_dir: Path) -> SignDatabase:
    db = SignDatabase()
    if db_dir.is_dir():
        for p in sorted(db_dir.glob("*.npz")):
            try:
                seq = SkeletonGraphSequence.load(p) if p.suffix == ".npz" and p.stat().st_size < 1_000_000 else from_npz(p)
            except Exception:
                try:
                    seq = from_npz(p)
                except Exception:
                    continue
            db.add(SignEntry(sign_id=p.stem, gloss=p.stem, sequence=seq))
    return db


def main() -> int:
    ap = argparse.ArgumentParser(description="SMPL-X EEMGM recognition (offline, Phase 5)")
    ap.add_argument("--query", required=True, help="query NPZ (smplx_joint_cam)")
    ap.add_argument("--database", required=True, help="sign database dir (NPZs) or single NPZ")
    ap.add_argument("--chunk", type=int, default=10)
    ap.add_argument("--threshold", type=float, default=0.2)
    args = ap.parse_args()

    q_path = Path(args.query)
    if not q_path.exists():
        print(f"query not found: {q_path}", file=sys.stderr)
        return 2

    try:
        query = from_npz(q_path)
    except Exception as exc:
        print(f"failed to load query {q_path}: {exc}", file=sys.stderr)
        return 2

    db_path = Path(args.database)
    db = SignDatabase()
    if db_path.is_file():
        try:
            seq = from_npz(db_path)
            db.add(SignEntry(sign_id=db_path.stem, gloss=db_path.stem, sequence=seq))
        except Exception as exc:
            print(f"failed to load db file {db_path}: {exc}", file=sys.stderr)
            return 2
    else:
        db = build_db(db_path)
        if len(db) == 0:
            print(f"database empty: {db_path} (put NPZs there; synthetic demo will use fallback)", file=sys.stderr)
            # fallback synthetic demo (so CLI always returns something)
            from .topology import SMPLX_NAMES
            import numpy as np

            rng = __import__("numpy").random.RandomState(0)
            pos = rng.randn(20, 55, 3).astype("float32") * 0.1
            demo = SkeletonGraphSequence(joint_names=SMPLX_NAMES, positions=pos, edges=__import__("offline.motion_analysis.topology", fromlist=["build_edges"]).build_edges(), fps=25.0)
            db.add(SignEntry(sign_id="demo_hello", gloss="HELLO", sequence=demo))

    res = eemgm(query, db, chunk_size=args.chunk, matching_threshold=args.threshold)
    out = {
        "query": str(q_path),
        "database": str(db_path),
        "predicted_sign": res.predicted_sign,
        "confidence": res.confidence,
        "early_estimated": res.early_estimated,
        "estimated_after_frame": res.estimated_after_frame,
        "frames_processed": res.frames_processed,
        "final_score": res.final_score,
        "candidate_scores": res.candidate_scores,
        "comparisons": res.comparisons,
        "elimination_history": res.elimination_history,
    }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
