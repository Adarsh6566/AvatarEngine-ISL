"""Build one canonical clip per sign from all of its takes.

    python -m offline.canonical.build --cache <takes-dir> --out offline/output/canonical

Writes a source_skeleton.v1 stream per sign, in the same shape the runtime
already loads from public/skeleton/. Per the offline contract this never edits
runtime files: it writes clips and prints a SignLibrary fragment for a human to
apply.

Every sign gets a report, because "the average" is only meaningful if the takes
actually agree. Two checks guard that:

  spread   pairwise warped distances between takes. A wide spread means the
           signers disagree, and the mean is a compromise none of them signs.
  split    quality of the best two-way split of the takes. A clean split is
           evidence of two distinct VARIANTS of the sign, where averaging is
           the wrong operation — it would interpolate between two correct
           performances and produce a third that is not either.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .dba import (
    barycenter,
    distance_matrix,
    dtw,
    enforce_bone_lengths,
    median_bone_lengths,
    medoid,
    resample,
    temporal_smooth,
)
from .takes import FINGER_TOKENS, Take, alignment_features, load_sign, signal_indices

SIGNS = ("good_evening", "good_night", "thank_you", "pleased")
GLOSS = {s: s.upper() for s in SIGNS}

# Signs whose takes disagree too much to average, with the shape of the correct
# performance so the right ones can be picked out. See pick_single_take().
#
# 'pleased' is fingers together and pointing up, then opening out. Its takes
# split hard on how far they open — peak fingertip spread runs 0.37 to 0.93, a
# 2.5x range, at a split score of 0.645 — and averaging them produced a
# half-open hand that performs neither. Even restricted to the seven takes that
# do open fully, the barycenter peaked at 0.61 against their median 0.83 and
# scored 5.8% worse than the best of them: the opening is a brief high-amplitude
# peak, and averaging peaks that differ in timing erodes them however well the
# warp is tuned.
VARIANT_SIGNS: dict[str, dict] = {
    "pleased": {"side": "r", "open_min": 0.70, "up_min": 0.55},
}


def handshape_curves(data: np.ndarray, joint_names: tuple[str, ...], side: str):
    """(pointing-up, fingertip-spread) per frame, for one hand.

    up      Y of the middle finger's direction; +1 is straight up.
    spread  mean fingertip separation over the knuckle span, so it measures
            opening independently of how big the hand is or how far away.
    """
    ix = {n: i for i, n in enumerate(joint_names)}
    need = [f"{side}Middle1", f"{side}Middle4", f"{side}Hand", f"{side}Index1"]
    if any(n not in ix for n in need):
        return np.zeros(len(data)), np.zeros(len(data))
    m1, m4, hand, k0 = (ix[n] for n in need)
    tips = [ix[f"{side}{f}4"] for f in ("Index", "Middle", "Ring", "Pinky") if f"{side}{f}4" in ix]

    up = np.zeros(len(data))
    spread = np.zeros(len(data))
    for t in range(len(data)):
        d = data[t, m4] - data[t, m1]
        n = np.linalg.norm(d)
        up[t] = d[1] / n if n > 1e-9 else 0.0
        pts = data[t, tips]
        pair = [
            np.linalg.norm(pts[i] - pts[j])
            for i in range(len(pts))
            for j in range(i + 1, len(pts))
        ]
        scale = np.linalg.norm(data[t, k0] - data[t, hand])
        spread[t] = (np.mean(pair) / scale) if scale > 1e-6 and pair else 0.0
    return up, spread


def pick_single_take(kept: list[Take], joint_names: tuple[str, ...], spec: dict):
    """The most representative take that actually performs the sign.

    Two filters, both from the sign's own definition rather than from which
    takes happen to look best: the hand must open (peak spread >= open_min) and
    must point up while still closed (before the spread peak). Among those, the
    medoid — closest to all the others — so the clip that ships is
    representative rather than merely the most dramatic.
    """
    side = spec["side"]
    correct = []
    for take in kept:
        up, spread = handshape_curves(take.data, joint_names, side)
        peak = int(np.argmax(spread))
        if spread.max() >= spec["open_min"] and peak > 0 and np.any(up[:peak] >= spec["up_min"]):
            correct.append(take)
    if not correct:
        return None, []
    feats = [alignment_features(t.data, joint_names) for t in correct]
    return correct[medoid(distance_matrix(feats))], correct


def two_way_split_quality(D: np.ndarray) -> tuple[float, list[int]]:
    """Best 2-medoid split, scored as (between - within) / between.

    Near 0 means one population. Above roughly 0.35 the two groups are further
    from each other than their members are from their own centre, which is the
    signature of genuinely different variants rather than noise.
    """
    n = D.shape[0]
    if n < 4:
        return 0.0, [0] * n
    best = (0.0, [0] * n)
    for a in range(n):
        for b in range(a + 1, n):
            labels = [0 if D[i, a] <= D[i, b] else 1 for i in range(n)]
            g0 = [i for i in range(n) if labels[i] == 0]
            g1 = [i for i in range(n) if labels[i] == 1]
            if len(g0) < 2 or len(g1) < 2:
                continue
            within = np.mean([D[i, a] for i in g0] + [D[i, b] for i in g1])
            between = D[a, b]
            if between <= 0:
                continue
            score = (between - within) / between
            if score > best[0]:
                best = (float(score), labels)
    return best


SIGMA_LADDER = (0.0, 0.4, 0.6, 0.8, 1.0, 1.4, 2.0)


def _finger_stats(data: np.ndarray, joint_names: tuple[str, ...]) -> tuple[float, float]:
    """(median per-frame finger movement, mean finger range of motion)."""
    f = [i for i, n in enumerate(joint_names) if any(t in n for t in FINGER_TOKENS)]
    step = np.linalg.norm(np.diff(data[:, f, :], axis=0), axis=2).mean(axis=1)
    rng = float(np.mean(data[:, f, :].max(axis=0) - data[:, f, :].min(axis=0)))
    return float(np.median(step)), rng


def choose_sigma(
    raw: np.ndarray,
    arrays: list[np.ndarray],
    joint_names: tuple[str, ...],
    parents: dict[str, str | None],
    lengths: dict[str, float],
) -> tuple[float, list[tuple[float, float, float]]]:
    """Smallest smoothing width that leaves the canonical no jitterier than a take.

    Handshape carries meaning, so range of motion is what must be protected;
    jitter only has to reach parity with a typical take, not be minimised. The
    ladder is walked from no smoothing upward and the first width that reaches
    parity wins, which is also the one that keeps the most range.
    """
    target = float(np.median([_finger_stats(a, joint_names)[0] for a in arrays]))
    trace: list[tuple[float, float, float]] = []
    chosen = SIGMA_LADDER[-1]
    for s in SIGMA_LADDER:
        cand = enforce_bone_lengths(temporal_smooth(raw, s), joint_names, parents, lengths)
        jit, rng = _finger_stats(cand, joint_names)
        trace.append((s, jit, rng))
        if jit <= target and chosen == SIGMA_LADDER[-1]:
            chosen = s
            break
    return chosen, trace


def build_sign(sign: str, cache: Path, out_dir: Path, sigma: float | None = None) -> dict:
    kept, rejected = load_sign(cache, sign)
    if len(kept) < 3:
        return {"sign": sign, "error": f"only {len(kept)} usable takes"}

    joint_names = kept[0].joint_names
    arrays = [t.data for t in kept]

    # Alignment runs on hand-relative finger features so handshape timing counts
    # for as much as arm travel; averaging still runs on raw positions.
    def featurize(a: np.ndarray) -> np.ndarray:
        return alignment_features(a, joint_names)

    feats = [featurize(a) for a in arrays]

    # Scoring stays in raw joint space — the space the runtime plays and the
    # viewer sees. Alignment features are a free choice; grading them in their
    # own space would only prove they optimise themselves.
    idx = signal_indices(joint_names)

    def raw_feat(a: np.ndarray) -> np.ndarray:
        return a[:, idx, :].reshape(a.shape[0], -1)

    raw_feats = [raw_feat(a) for a in arrays]

    n_frames = int(np.median([t.n_frames for t in kept]))
    fps = float(np.median([t.fps for t in kept]))

    D = distance_matrix(feats)
    off = D[~np.eye(len(arrays), dtype=bool)]
    split_score, labels = two_way_split_quality(D)
    med_i = medoid(D)

    # A sign whose takes disagree ships a real performance instead of their mean.
    spec = VARIANT_SIGNS.get(sign)
    if spec:
        pick, correct = pick_single_take(kept, joint_names, spec)
        if pick is not None:
            write_stream(out_dir / f"{sign}.json", pick.data, joint_names,
                         {j["name"]: j.get("parent") for j in _meta_of(cache, sign)["joints"]},
                         pick.fps, sign, [pick], single=pick.name,
                         candidates=[t.name for t in correct])
            idx0 = signal_indices(joint_names)
            rf = [a[:, idx0, :].reshape(len(a), -1) for a in arrays]
            score = float(np.mean([dtw(pick.data[:, idx0, :].reshape(pick.n_frames, -1), r)[0] for r in rf]))
            up, spread = handshape_curves(pick.data, joint_names, spec["side"])
            return {
                "sign": sign, "mode": "single take", "take": pick.name,
                "takes_used": len(kept), "candidates": [t.name for t in correct],
                "takes_rejected": [(t.name, round(t.dropout, 3)) for t in rejected],
                "frames": pick.n_frames, "fps": pick.fps,
                "spread_mean": float(off.mean()), "spread_std": float(off.std()),
                "split_score": split_score, "split_sizes": [labels.count(0), labels.count(1)],
                "canonical_score": score, "peak_spread": float(spread.max()),
                "max_up_before_peak": float(up[: int(np.argmax(spread))].max()) if np.argmax(spread) else 0.0,
            }

    raw, history = barycenter(arrays, featurize, n_frames)

    parents = {j["name"]: j.get("parent") for j in _meta_of(cache, sign)["joints"]}
    lengths = median_bone_lengths(arrays, joint_names, parents)

    used_sigma, sigma_trace = (
        choose_sigma(raw, arrays, joint_names, parents, lengths)
        if sigma is None
        else (sigma, [])
    )

    # Order matters: damp the warp's frame-to-frame wobble first, then make the
    # skeleton rigid. Smoothing after the bone fix would reintroduce length
    # error by averaging neighbouring positions again.
    canonical = enforce_bone_lengths(
        temporal_smooth(raw, used_sigma), joint_names, parents, lengths
    )
    canon_jitter, canon_range = _finger_stats(canonical, joint_names)
    take_jitter, take_range = (
        float(np.median([_finger_stats(a, joint_names)[0] for a in arrays])),
        float(np.median([_finger_stats(a, joint_names)[1] for a in arrays])),
    )

    # How well does each candidate represent the set? Lower is better.
    def mean_distance(seq: np.ndarray) -> float:
        sf = raw_feat(seq)
        return float(np.mean([dtw(sf, f)[0] for f in raw_feats]))

    canon_score = mean_distance(canonical)
    medoid_score = mean_distance(resample(arrays[med_i], n_frames))
    per_take = [mean_distance(a) for a in arrays]
    best_take_score = float(np.min(per_take))
    best_take = kept[int(np.argmin(per_take))].name

    write_stream(out_dir / f"{sign}.json", canonical, joint_names, parents, fps, sign, kept)

    return {
        "sign": sign,
        "takes_used": len(kept),
        "takes_rejected": [(t.name, round(t.dropout, 3)) for t in rejected],
        "frames": n_frames,
        "fps": fps,
        "spread_mean": float(off.mean()),
        "spread_std": float(off.std()),
        "split_score": split_score,
        "split_sizes": [labels.count(0), labels.count(1)],
        "canonical_score": canon_score,
        "medoid_score": medoid_score,
        "best_take": best_take,
        "best_take_score": best_take_score,
        "improvement_vs_best_take": (best_take_score - canon_score) / best_take_score,
        "dba_history": [round(h, 5) for h in history],
        "sigma": used_sigma,
        "sigma_trace": [(s_, round(j, 5), round(r, 4)) for s_, j, r in sigma_trace],
        "canon_jitter": canon_jitter,
        "take_jitter": take_jitter,
        "canon_range": canon_range,
        "take_range": take_range,
    }


def _meta_of(cache: Path, sign: str) -> dict:
    path = next((cache / sign).glob("*.json"))
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["meta"]


def write_stream(
    path: Path,
    data: np.ndarray,
    joint_names: tuple[str, ...],
    parents: dict[str, str | None],
    fps: float,
    sign: str,
    sources: list[Take],
    single: str | None = None,
    candidates: list[str] | None = None,
) -> None:
    n = data.shape[0]
    payload = {
        "meta": {
            "schema": "source_skeleton.v1 → view",
            "space": "view (Y-up, root-centered at hips, unit = mean hip→head)",
            "fps": fps,
            "frameCount": n,
            "duration": round(n / fps, 4),
            "joints": [{"name": nm, "parent": parents.get(nm)} for nm in joint_names],
            "source_video": f"{single}.MOV" if single else f"canonical of {len(sources)} takes",
            "estimator": "mediapipe tasks pose+hand (lite) + smoothed"
            + ("" if single else " + DTW barycenter"),
            "gloss": GLOSS[sign],
            "coordinate_space": "world (Y down, meters, cheap-3D)",
            "canonical": {
                "method": "single take, medoid of those performing the sign"
                if single
                else "DTW barycenter averaging, trimmed mean, bone-length enforced",
                "takes": candidates if single else [t.name for t in sources],
            },
        },
        "frames": [
            {
                "index": i,
                "timestamp": round(i / fps, 4),
                "joints": {
                    nm: [round(float(c), 6) for c in data[i, j]] + [1.0]
                    for j, nm in enumerate(joint_names)
                },
            }
            for i in range(n)
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True, type=Path, help="dir of <sign>/<take>.json")
    ap.add_argument("--out", type=Path, default=Path("offline/output/canonical"))
    ap.add_argument("--signs", nargs="*", default=list(SIGNS))
    ap.add_argument("--sigma", type=float, default=None,
                    help="temporal smoothing in frames; omit to auto-select per sign")
    args = ap.parse_args()

    reports = []
    for sign in args.signs:
        print(f"\n=== {sign} ===", flush=True)
        r = build_sign(sign, args.cache, args.out, args.sigma)
        reports.append(r)
        if "error" in r:
            print(f"  SKIPPED: {r['error']}")
            continue
        if r.get("mode") == "single take":
            print(f"  MODE               single take (takes disagree; split {r['split_score']:.3f})")
            print(f"  chosen             {r['take']}  from {len(r['candidates'])} performing it correctly")
            print(f"  frames             {r['frames']} @ {r['fps']:.0f}fps")
            print(f"  peak spread        {r['peak_spread']:.2f}   points up first {r['max_up_before_peak']:+.2f}")
            print(f"  score              {r['canonical_score']:.4f}")
            continue
        print(f"  takes used         {r['takes_used']}  (rejected {len(r['takes_rejected'])})")
        for name, drop in r["takes_rejected"]:
            print(f"    rejected {name}  dropout {drop*100:.0f}%")
        print(f"  frames             {r['frames']} @ {r['fps']:.0f}fps")
        print(f"  take spread        {r['spread_mean']:.4f} +/- {r['spread_std']:.4f}")
        print(f"  2-way split score  {r['split_score']:.3f}  sizes {r['split_sizes']}")
        print(f"  best single take   {r['best_take']}  score {r['best_take_score']:.4f}")
        print(f"  medoid             score {r['medoid_score']:.4f}")
        print(f"  CANONICAL          score {r['canonical_score']:.4f}"
              f"   ({r['improvement_vs_best_take']*100:+.1f}% vs best take)")
        print(f"  smoothing sigma    {r['sigma']}  (auto)")
        print(f"  finger jitter      {r['canon_jitter']:.5f} vs takes {r['take_jitter']:.5f}"
              f"  {'OK' if r['canon_jitter'] <= r['take_jitter'] else 'HIGH'}")
        print(f"  finger range       {r['canon_range']:.4f} vs takes {r['take_range']:.4f}"
              f"  ({r['canon_range']/r['take_range']*100:.0f}% retained)")

    print("\n=== SignLibrary fragment ===")
    for r in reports:
        if "error" in r:
            continue
        s = r["sign"]
        print(f"  {{ gloss: '{GLOSS[s]}', path: '/skeleton/{s}.json', words: [...] }},")

    with open(args.out / "report.json", "w", encoding="utf-8") as fh:
        json.dump(reports, fh, indent=2)
    print(f"\nreport -> {args.out / 'report.json'}")


if __name__ == "__main__":
    main()
