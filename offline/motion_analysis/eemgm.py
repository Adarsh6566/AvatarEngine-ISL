"""EEMGM — paper early estimation, offline research only (Phase 4).

SignDatabase + 10-frame chunks + elimination. Does NOT touch production translator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
import numpy as np

from .graph import SkeletonGraphSequence
from .graph_matching import compare_sequences


@dataclass
class SignEntry:
    sign_id: str
    gloss: str
    sequence: SkeletonGraphSequence
    motion_indices: np.ndarray | None = None
    fps: float = 25.0
    metadata: dict = field(default_factory=dict)


class SignDatabase:
    def __init__(self) -> None:
        self.entries: list[SignEntry] = []

    def add(self, entry: SignEntry) -> None:
        self.entries.append(entry)

    def load_from_dir(self, directory: str | Path) -> None:
        p = Path(directory)
        for npz in p.glob("*.npz"):
            try:
                seq = SkeletonGraphSequence.load(npz)
                self.add(SignEntry(sign_id=npz.stem, gloss=npz.stem, sequence=seq))
            except Exception:
                continue

    def __len__(self) -> int:
        return len(self.entries)


@dataclass(frozen=True)
class EEMGMResult:
    predicted_sign: str | None
    confidence: float
    candidate_scores: dict[str, float]
    elimination_history: list[dict]
    frames_processed: int
    early_estimated: bool
    estimated_after_frame: int | None
    final_score: float | None
    comparisons: int


def _frame_match_score(q_seq: SkeletonGraphSequence, d_seq: SkeletonGraphSequence, q_chunk: slice, d_limit: int | None = None) -> tuple[float, int, int]:
    """Compare early portion: count sufficiently similar frames + avg score. Returns (avg, count, total)."""
    sub_q = SkeletonGraphSequence(joint_names=q_seq.joint_names, positions=q_seq.positions[q_chunk], edges=q_seq.edges, fps=q_seq.fps)
    # dataset early portion: first len(chunk) frames or d_limit
    d_end = min(d_seq.frame_count, q_chunk.stop - q_chunk.start if d_limit is None else d_limit)
    sub_d = SkeletonGraphSequence(joint_names=d_seq.joint_names, positions=d_seq.positions[:d_end], edges=d_seq.edges, fps=d_seq.fps)
    mats = compare_sequences(sub_q, sub_d)
    Mc = mats["combined"]  # (q_chunk_len, d_end)
    # For each query frame, best match (min distance) in dataset early portion
    best = Mc.min(axis=1) if Mc.size else np.array([])
    avg = float(best.mean()) if best.size else float("inf")
    # matching threshold ~0.2 (paper), configurable; count frames with distance < threshold
    # Use 0.08 for normalized coords (scale); caller passes threshold
    return avg, int((best < 0.2).sum()), int(best.size)


def eemgm(
    query: SkeletonGraphSequence,
    database: SignDatabase,
    chunk_size: int = 10,
    matching_threshold: float = 0.2,
    consecutive_required: int = 5,
) -> EEMGMResult:
    """Paper EEMGM. Chunk query into 10-frame pieces, eliminate candidates.

    Exposes matching_threshold and consecutive_required as config (paper reports 0.2 and ~5).
    """
    candidates = list(database.entries)
    history: list[dict] = []
    comparisons = 0
    estimated_after: int | None = None
    early = False

    total_chunks = (query.frame_count + chunk_size - 1) // chunk_size
    frames_processed = 0

    for k in range(total_chunks):
        q_slice = slice(k * chunk_size, min((k + 1) * chunk_size, query.frame_count))
        chunk_len = q_slice.stop - q_slice.start
        frames_processed = q_slice.stop

        scores: dict[str, float] = {}
        keep: list[SignEntry] = []
        for entry in candidates:
            mats = compare_sequences(
                SkeletonGraphSequence(joint_names=query.joint_names, positions=query.positions[q_slice], edges=query.edges, fps=query.fps),
                SkeletonGraphSequence(joint_names=entry.sequence.joint_names, positions=entry.sequence.positions[:chunk_len], edges=entry.sequence.edges, fps=entry.sequence.fps),
            )
            comparisons += chunk_len * min(chunk_len, entry.sequence.frame_count)
            Mc = mats["combined"]
            best = Mc.min(axis=1) if Mc.size else np.array([])
            avg = float(best.mean()) if best.size else float("inf")
            cnt = int((best < matching_threshold).sum()) if best.size else 0
            scores[entry.sign_id] = avg
            # Keep if sufficiently similar: avg < threshold and enough consecutive matches
            if avg < matching_threshold and cnt >= min(consecutive_required, chunk_len):
                keep.append(entry)

        history.append({"chunk": k, "candidates_before": len(candidates), "candidates_after": len(keep), "scores": dict(scores)})
        # If no one passes, keep best one to avoid empty
        if not keep and scores:
            best_id = min(scores, key=lambda kk: scores[kk])
            if scores[best_id] < matching_threshold * 2:
                keep = [e for e in candidates if e.sign_id == best_id]

        candidates = keep
        if len(candidates) == 1:
            early = True
            estimated_after = frames_processed
            break
        if not candidates:
            break

    # Final validation on remaining query frames if early
    final_score: float | None = None
    predicted: str | None = None
    candidate_scores: dict[str, float] = {}
    for e in (candidates if candidates else database.entries):
        mats = compare_sequences(query, e.sequence)
        Mc = mats["combined"]
        avg = float(Mc.min(axis=1).mean()) if Mc.size else float("inf")
        candidate_scores[e.sign_id] = avg
    if candidate_scores:
        predicted = min(candidate_scores, key=lambda k: candidate_scores[k])
        final_score = candidate_scores[predicted]
        # Never return high confidence if similarity poor
        if final_score is not None and final_score > matching_threshold * 1.5:
            early = False

    conf = 1.0 / (1.0 + (final_score or 1.0))
    return EEMGMResult(
        predicted_sign=predicted,
        confidence=float(conf),
        candidate_scores=candidate_scores,
        elimination_history=history,
        frames_processed=frames_processed,
        early_estimated=early,
        estimated_after_frame=estimated_after,
        final_score=final_score,
        comparisons=comparisons,
    )


def compare_full_vs_eemgm(query: SkeletonGraphSequence, database: SignDatabase) -> dict:
    """Measure full vs EEMGM comparisons, time, speedup."""
    t0 = time.perf_counter()
    full_comps = 0
    for e in database.entries:
        mats = compare_sequences(query, e.sequence)
        full_comps += mats["combined"].size
    t_full = time.perf_counter() - t0

    t1 = time.perf_counter()
    res = eemgm(query, database)
    t_eem = time.perf_counter() - t1
    return {
        "full_comparisons": full_comps,
        "eemgm_comparisons": res.comparisons,
        "full_time": t_full,
        "eemgm_time": t_eem,
        "speedup": t_full / max(t_eem, 1e-9),
        "reduction": 1 - res.comparisons / max(full_comps, 1),
        "eemgm_result": res,
    }
