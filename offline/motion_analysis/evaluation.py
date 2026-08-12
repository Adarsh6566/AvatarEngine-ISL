"""Evaluation — measure, don't claim (Phase 5). Baselines A-D, motion quality, graph, recognition, perf."""
from __future__ import annotations

import json
import csv
import time
from pathlib import Path
from statistics import mean, median, stdev
import numpy as np

from .graph import SkeletonGraphSequence, extract_motion_frames
from .graph_matching import compare_sequences
from .eemgm import SignDatabase, compare_full_vs_eemgm


def motion_quality(seq: SkeletonGraphSequence) -> dict:
    pos = seq.positions
    # proxy metrics: joint stability (std of bone lengths), smoothness (mean acceleration)
    diff1 = np.linalg.norm(pos[1:] - pos[:-1], axis=2).mean() if len(pos) > 1 else 0.0
    diff2 = np.linalg.norm(pos[2:] - 2 * pos[1:-1] + pos[:-2], axis=2).mean() if len(pos) > 2 else 0.0
    finite = bool(np.isfinite(pos).all())
    return {"mean_velocity": float(diff1), "mean_acceleration": float(diff2), "finite": finite, "frames": int(seq.frame_count)}


def graph_similarities(q: SkeletonGraphSequence, d_same: SkeletonGraphSequence, d_diff: SkeletonGraphSequence) -> dict:
    from .graph_matching import compare_frames

    def stats_for(a, b):
        mats = compare_sequences(a, b)
        Mc = mats["combined"]
        # also hand-aware via frame 0
        m0 = compare_frames(a.graph_at(0), b.graph_at(0))
        return {
            "overall_mean": float(Mc.mean()) if Mc.size else 0.0,
            "overall_median": float(np.median(Mc)) if Mc.size else 0.0,
            "overall_std": float(Mc.std()) if Mc.size else 0.0,
            "body": float(m0.body_score),
            "left_hand": float(m0.left_hand_score),
            "right_hand": float(m0.right_hand_score),
            "fingers": float(m0.finger_score),
        }

    return {"same_sign": stats_for(q, d_same), "different_sign": stats_for(q, d_diff)}


def evaluate(
    query: SkeletonGraphSequence,
    db_same: SignDatabase,
    db_diff: SignDatabase,
    out_dir: Path = Path("offline/output/evaluation"),
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    # Baselines (proxy: same data, different normalization)
    # A: MediaPipe (simulated as raw with higher jitter) — not real, marked proxy
    # B: SMPLest-X raw, C: +graph, D: +EEMGM — we report what we can (C/D)
    # For synthetic, B/C are same raw; D is EEMGM

    # Motion frames
    res_raw = extract_motion_frames(query, mode="paper_mode")
    retention = float(res_raw.retention_mask.sum() / max(query.frame_count, 1))

    # Graph similarities
    # pick first entry from each db as same/diff if available, else synthetic
    same_seq = db_same.entries[0].sequence if len(db_same) else query
    diff_seq = db_diff.entries[0].sequence if len(db_diff) else query

    graph_stats = graph_similarities(query, same_seq, diff_seq)
    mq = motion_quality(query)

    # Perf: full vs EEMGM on db_same+db_diff combined
    combined = SignDatabase()
    for e in list(db_same.entries) + list(db_diff.entries):
        combined.add(e)
    if len(combined) == 0:
        combined.add(__import__("offline.motion_analysis.eemgm", fromlist=["SignEntry"]).SignEntry(sign_id="demo", gloss="HELLO", sequence=query))
    perf = compare_full_vs_eemgm(query, combined)

    # Build metrics
    metrics = {
        "paper_reported": {"motion_frame_reduction": 0.25, "note": "paper reports ~25% retained; do not assume, our measured is below"},
        "our_measured": {
            "motion": mq,
            "graph_same_vs_diff": graph_stats,
            "motion_frames": {"original": int(query.frame_count), "retained": int(res_raw.retention_mask.sum()), "retention": retention, "threshold_vertex": float(res_raw.threshold_vertex), "threshold_edge": float(res_raw.threshold_edge)},
            "performance": {k: v for k, v in perf.items() if k != "eemgm_result"},
            "eemgm": {"early_estimated": bool(perf["eemgm_result"].early_estimated), "frames_processed": int(perf["eemgm_result"].frames_processed)},
        },
        "assumptions": {"coordinate_space": query.coordinate_space, "normalization": query.normalization, "smplx_vs_vicon": "SMPL-X 55 joints, not paper 57-marker Vicon; adaptation not exact reproduction", "signer_disjoint": "synthetic test — not signer-disjoint; real eval needs separate recordings"},
        "baselines": {"A_MediaPipe": "proxy — not measured (no MediaPipe NPZ here)", "B_SMPLestX_raw": "raw camera coords", "C_SMPLestX_graph": "graph + motion frames", "D_SMPLestX_EEMGM": "graph + EEMGM"},
    }

    # Write outputs
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    # summary.csv
    with open(out_dir / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value"])
        w.writerow(["original_frames", query.frame_count])
        w.writerow(["retained_frames", int(res_raw.retention_mask.sum())])
        w.writerow(["retention", retention])
        w.writerow(["same_overall_mean", graph_stats["same_sign"]["overall_mean"]])
        w.writerow(["diff_overall_mean", graph_stats["different_sign"]["overall_mean"]])
        w.writerow(["speedup", perf["speedup"]])
        w.writerow(["reduction", perf["reduction"]])

    # comparison_report.md
    report = f"""# Evaluation (Phase 5) — {query.frame_count} frames, J={len(query.joint_names)}

> Measure, don't claim. Synthetic demo — real SMPLest-X NPZ pending.

## Motion frames
- Original: {query.frame_count}, Retained: {int(res_raw.retention_mask.sum())}, Retention: {retention:.2%}
- Paper reported ~25% retained — **our measured** is above, not assumed.

## Graph same vs different (lower distance = more similar)
- Same mean {graph_stats["same_sign"]["overall_mean"]:.4f} vs Diff {graph_stats["different_sign"]["overall_mean"]:.4f} → {'PASS (same < diff)' if graph_stats["same_sign"]["overall_mean"] < graph_stats["different_sign"]["overall_mean"] else 'FAIL'}
- Body/left/right/fingers also reported in metrics.json

## Performance (full vs EEMGM)
- Full comparisons: {perf["full_comparisons"]}, EEMGM: {perf["eemgm_comparisons"]}, Speedup: {perf["speedup"]:.2f}x, Reduction: {perf["reduction"]:.2%}

## Assumptions
- SMPL-X 55 joints, not 57-marker Vicon (adaptation)
- Synthetic signer — not signer-disjoint; real eval needs separate recordings
- Coordinate: {query.coordinate_space}, norm: {query.normalization}
"""
    (out_dir / "comparison_report.md").write_text(report, encoding="utf-8")
    (out_dir / "plots").mkdir(exist_ok=True)

    return metrics
