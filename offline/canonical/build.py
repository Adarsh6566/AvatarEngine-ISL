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
    despike,
    distance_matrix,
    dtw,
    enforce_bone_lengths,
    median_bone_lengths,
    medoid,
    resample,
    temporal_smooth,
)
from .hands import MAX_UNSOLVED_FRACTION, blend_hands, stabilize_hands, unsolved_fraction
from .takes import FINGER_TOKENS, Take, alignment_features, load_sign, signal_indices

SIGNS = (
    # Greetings_1of2
    "hello",
    "how_are_you",
    "alright",
    "good_morning",
    "good_afternoon",
    # Greetings_2of2
    "good_evening",
    "good_night",
    "thank_you",
    "pleased",
    # Pronouns_2of2
    "we",
    "you_plural",
    "they",
)
GLOSS = {s: s.upper() for s in SIGNS}


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


ARM_STAT_JOINTS = ("lElbow", "lWrist", "lHand", "rElbow", "rWrist", "rHand")


def _group_indices(joint_names: tuple[str, ...]) -> dict[str, list[int]]:
    """The joint groups jitter is judged on: the fingers, and the arm carrying them."""
    return {
        "fingers": [i for i, n in enumerate(joint_names) if any(t in n for t in FINGER_TOKENS)],
        "arm": [i for i, n in enumerate(joint_names) if n in ARM_STAT_JOINTS],
    }


def _motion_stats(
    data: np.ndarray, joint_names: tuple[str, ...]
) -> tuple[dict[str, dict[str, float]], float]:
    """(per-group step statistics, mean finger range of motion).

    Each group reports both the MEDIAN step and the 95th percentile, because
    they describe different faults and only the second is what gets complained
    about. The median is the general noise level; p95 is the fast lurch — the
    handful of frames that move several times as far as the rest, which read as
    sudden wrong motion and can carry a hand into the body before the next
    frame pulls it back.

    Both groups are measured, fingers and the arm carrying them, since a calm
    hand on a lurching wrist still looks wrong.
    """
    groups = _group_indices(joint_names)
    steps: dict[str, dict[str, float]] = {}
    for name, idx in groups.items():
        if not idx:
            continue
        step = np.linalg.norm(np.diff(data[:, idx, :], axis=0), axis=2).mean(axis=1)
        steps[name] = {
            "median": float(np.median(step)),
            "p95": float(np.percentile(step, 95)),
        }
    f = groups["fingers"]
    rng = float(np.mean(data[:, f, :].max(axis=0) - data[:, f, :].min(axis=0))) if f else 0.0
    return steps, rng


def _finger_stats(data: np.ndarray, joint_names: tuple[str, ...]) -> tuple[float, float]:
    """(median per-frame finger movement, mean finger range of motion)."""
    steps, rng = _motion_stats(data, joint_names)
    return steps.get("fingers", {}).get("median", 0.0), rng


def finish(
    raw: np.ndarray,
    sigma: float,
    joint_names: tuple[str, ...],
    parents: dict[str, str | None],
    lengths: dict[str, float],
    fps: float,
) -> np.ndarray:
    """The post-averaging chain, in the one order that works.

    Damp the warp's frame-to-frame wobble first, then repair the hand, then make
    the skeleton rigid. Smoothing after the bone fix would reintroduce length
    error by averaging neighbouring positions again, and the bone fix has to be
    last because the hand repair moves finger positions.

    The hand repair runs here as well as on the takes, because averaging puts
    the artefact BACK. Each take can be clean and the barycenter still swing the
    palm 177 degrees between two frames: positions are averaged per joint, which
    does not preserve a rotation, so where warp membership changes between
    adjacent reference frames the mean hand frame jumps. Repairing the inputs
    alone measurably did not fix the output — this was checked, not assumed.
    """
    out = enforce_bone_lengths(temporal_smooth(despike(raw), sigma), joint_names, parents, lengths)
    out, _ = stabilize_hands(out, joint_names, parents, fps)
    return out


def choose_sigma(
    raw: np.ndarray,
    arrays: list[np.ndarray],
    joint_names: tuple[str, ...],
    parents: dict[str, str | None],
    lengths: dict[str, float],
    fps: float,
) -> tuple[float, list[tuple[float, float, float]]]:
    """Smallest smoothing width that leaves the canonical no jitterier than a take.

    Handshape carries meaning, so range of motion is what must be protected;
    jitter only has to reach parity with a typical take, not be minimised. The
    ladder is walked from no smoothing upward and the first width that reaches
    parity wins, which is also the one that keeps the most range.

    Parity is required on the ARM as well as the fingers. Requiring it of the
    fingers alone left the arms unmeasured, and they were the worse offender:
    the published clips carried wrist steps up to 7.6x their own median, which
    reads as a fast wrong motion and can drive the hand into the body for a
    frame. The arm is also the cheaper one to smooth — it has none of the
    handshape detail that smoothing costs.
    """
    per_take = [_motion_stats(a, joint_names)[0] for a in arrays]
    # Parity is judged against the takes on BOTH statistics of BOTH groups. p95
    # is the one that matters for the lurches; median alone was satisfied by
    # clips that still jumped, and worse, lowering the median (as despiking
    # does) then let this pick LESS smoothing and leave the jumps bigger.
    targets = {
        (g, stat): float(np.median([s[g][stat] for s in per_take if g in s]))
        for g in ("fingers", "arm")
        for stat in ("median", "p95")
        if any(g in s for s in per_take)
    }
    trace: list[tuple[float, float, float]] = []
    chosen = SIGMA_LADDER[-1]
    for s in SIGMA_LADDER:
        cand = finish(raw, s, joint_names, parents, lengths, fps)
        steps, rng = _motion_stats(cand, joint_names)
        trace.append((s, steps.get("fingers", {}).get("median", 0.0), rng))
        met = all(
            steps.get(g, {}).get(stat, 0.0) <= target for (g, stat), target in targets.items()
        )
        if met and chosen == SIGMA_LADDER[-1]:
            chosen = s
            break
    return chosen, trace


def build_sign(sign: str, cache: Path, out_dir: Path, sigma: float | None = None) -> dict:
    kept, rejected = load_sign(cache, sign)
    if len(kept) < 3:
        return {"sign": sign, "error": f"only {len(kept)} usable takes"}

    joint_names = kept[0].joint_names
    parents = {j["name"]: j.get("parent") for j in _meta_of(cache, sign)["joints"]}

    # Repair each take's hand before anything reads it. The palm solve is
    # ambiguous on a hand that is moving or edge-on, and the tracker flips
    # between its two answers — up to 179 degrees in one 1/25s frame, which no
    # wrist can do. It has to happen here, before alignment and before
    # averaging: the warp aligns partly on finger positions, so a flipped frame
    # mismatches handshapes and steers the warp, and averaging then spreads one
    # take's bad frame across the template.
    # Screen on the hand before repairing it. A take whose palm was never
    # solved is not a noisier input, it is a wrong one, and the repair would be
    # inventing most of the performance rather than mending it — measured up to
    # 96% of frames on one recording. This rejects the same takes the earlier
    # ablation could only describe as a "systematic outlier session": they are
    # the ones where hand tracking failed, which is why they sit apart on every
    # sign at once.
    unsolved = [unsolved_fraction(t.data, joint_names, parents, t.fps) for t in kept]
    hand_rejected = [
        (t.name, round(u, 3)) for t, u in zip(kept, unsolved) if u > MAX_UNSOLVED_FRACTION
    ]
    kept = [t for t, u in zip(kept, unsolved) if u <= MAX_UNSOLVED_FRACTION]
    if len(kept) < 3:
        return {"sign": sign, "error": f"only {len(kept)} takes with a usable hand"}

    repairs = []
    arrays = []
    for t in kept:
        fixed, rep = stabilize_hands(t.data, joint_names, parents, t.fps)
        arrays.append(fixed)
        repairs.append(max((v["fraction"] for v in rep.values()), default=0.0))

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

    raw, history = barycenter(
        arrays,
        featurize,
        n_frames,
        refine=lambda members, mean: blend_hands(members, mean, joint_names, parents),
    )

    lengths = median_bone_lengths(arrays, joint_names, parents)

    used_sigma, sigma_trace = (
        choose_sigma(raw, arrays, joint_names, parents, lengths, fps)
        if sigma is None
        else (sigma, [])
    )

    canonical = finish(raw, used_sigma, joint_names, parents, lengths, fps)
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
        "hand_rejected": hand_rejected,
        "hand_repair_mean": float(np.mean(repairs)) if repairs else 0.0,
        "hand_repair_max": float(np.max(repairs)) if repairs else 0.0,
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
            "source_video": f"canonical of {len(sources)} takes",
            "estimator": "mediapipe tasks pose+hand (lite) + smoothed + DTW barycenter",
            "gloss": GLOSS[sign],
            "coordinate_space": "world (Y down, meters, cheap-3D)",
            "canonical": {
                "method": "DTW barycenter averaging, trimmed mean, bone-length enforced",
                "takes": [t.name for t in sources],
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
        print(f"  takes used         {r['takes_used']}  (rejected {len(r['takes_rejected'])})")
        for name, drop in r["takes_rejected"]:
            print(f"    rejected {name}  dropout {drop*100:.0f}%")
        print(f"  frames             {r['frames']} @ {r['fps']:.0f}fps")
        for name, frac in r["hand_rejected"]:
            print(f"    rejected {name}  hand unsolved {frac*100:.0f}%")
        print(f"  hand frames fixed  {r['hand_repair_mean']*100:.1f}% mean,"
              f" {r['hand_repair_max']*100:.1f}% worst take")
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
