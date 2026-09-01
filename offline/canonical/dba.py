"""DTW barycenter averaging — the canonical motion of a set of takes.

Two signers perform the same sign at different speeds and with different pauses,
so averaging frame k of every take against frame k of every other would blend a
hand that is still rising against one already held. Dynamic time warping fixes
that by matching each take to a reference along the path of least total
distance, and the barycenter is the average under those warps.

Iterating alignment and averaging (DBA, Petitjean et al.) converges to a
sequence that minimises the mean warped distance to the whole set — which is
the precise sense in which the result is the "average performance" rather than
any one signer's.

This is unsupervised template estimation, not a trained network. At twenty
takes per sign, a network with enough capacity to model motion would memorise
the takes; averaging has no parameters to overfit.
"""

from __future__ import annotations

import numpy as np


def _flat(data: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """(T, J, 3) -> (T, len(idx)*3), the vector DTW compares."""
    return data[:, idx, :].reshape(data.shape[0], -1)


def cost_matrix(a: np.ndarray, b: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """Pairwise frame distance, (Ta, Tb).

    Euclidean over the stacked signal joints, so a frame differing in one finger
    costs less than one differing across the whole hand.
    """
    A, B = _flat(a, idx), _flat(b, idx)
    sq = (A * A).sum(1)[:, None] + (B * B).sum(1)[None, :] - 2.0 * (A @ B.T)
    return np.sqrt(np.maximum(sq, 0.0))


def dtw(a: np.ndarray, b: np.ndarray, idx: np.ndarray) -> tuple[float, list[tuple[int, int]]]:
    """Warped distance and alignment path between two takes.

    Endpoints are anchored: every take starts at rest and ends at rest, so the
    first and last frames must correspond. The path is returned start-to-end.
    """
    C = cost_matrix(a, b, idx)
    n, m = C.shape
    D = np.full((n + 1, m + 1), np.inf)
    D[0, 0] = 0.0
    for i in range(1, n + 1):
        # D[i, j] depends on D[i, j-1], so this row cannot be vectorised.
        row, prev = D[i], D[i - 1]
        ci = C[i - 1]
        for j in range(1, m + 1):
            row[j] = ci[j - 1] + min(prev[j], row[j - 1], prev[j - 1])

    path: list[tuple[int, int]] = []
    i, j = n, m
    while i > 0 and j > 0:
        path.append((i - 1, j - 1))
        step = min(D[i - 1, j], D[i, j - 1], D[i - 1, j - 1])
        if step == D[i - 1, j - 1]:
            i, j = i - 1, j - 1
        elif step == D[i - 1, j]:
            i -= 1
        else:
            j -= 1
    path.reverse()
    # Normalised by path length so takes of different duration compare fairly.
    return float(D[n, m] / max(len(path), 1)), path


def resample(data: np.ndarray, n: int) -> np.ndarray:
    """Uniformly resample a take to n frames by linear interpolation."""
    t_src = np.linspace(0.0, 1.0, data.shape[0])
    t_dst = np.linspace(0.0, 1.0, n)
    out = np.empty((n, data.shape[1], data.shape[2]), dtype=data.dtype)
    for j in range(data.shape[1]):
        for c in range(data.shape[2]):
            out[:, j, c] = np.interp(t_dst, t_src, data[:, j, c])
    return out


def distance_matrix(takes: list[np.ndarray], idx: np.ndarray) -> np.ndarray:
    """Symmetric matrix of pairwise warped distances."""
    n = len(takes)
    D = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            d, _ = dtw(takes[i], takes[j], idx)
            D[i, j] = D[j, i] = d
    return D


def medoid(D: np.ndarray) -> int:
    """Index of the take closest to all the others — the DBA seed.

    Seeding from the medoid rather than an arbitrary take matters: DBA descends
    to a local optimum, and starting from an outlier converges to a shape no
    signer actually performed.
    """
    return int(np.argmin(D.sum(axis=1)))


def _trimmed_mean(stack: np.ndarray, trim: float) -> np.ndarray:
    """Mean of stack (N, ...) after dropping the most extreme trim fraction.

    Extremeness is per group, by distance from the group median, so a take that
    is an outlier only at one instant is dropped only there.
    """
    n = stack.shape[0]
    k = int(np.floor(n * trim))
    if n <= 2 or k <= 0:
        return stack.mean(axis=0)
    med = np.median(stack, axis=0)
    dist = np.linalg.norm((stack - med).reshape(n, -1), axis=1)
    keep = np.argsort(dist)[: n - k]
    return stack[keep].mean(axis=0)


def barycenter(
    takes: list[np.ndarray],
    idx: np.ndarray,
    n_frames: int,
    iters: int = 12,
    trim: float = 0.2,
    tol: float = 1e-5,
) -> tuple[np.ndarray, list[float]]:
    """Iteratively align every take to the running mean, then re-average.

    Returns the canonical sequence and the mean warped distance after each
    iteration, which should decrease monotonically.
    """
    D = distance_matrix(takes, idx)
    ref = resample(takes[medoid(D)], n_frames).copy()

    history: list[float] = []
    for _ in range(iters):
        groups: list[list[np.ndarray]] = [[] for _ in range(n_frames)]
        total = 0.0
        for take in takes:
            d, path = dtw(ref, take, idx)
            total += d
            for r, t in path:
                groups[r].append(take[t])

        nxt = np.empty_like(ref)
        for r in range(n_frames):
            nxt[r] = _trimmed_mean(np.stack(groups[r]), trim) if groups[r] else ref[r]

        shift = float(np.abs(nxt - ref).mean())
        ref = nxt
        history.append(total / len(takes))
        if shift < tol:
            break

    return ref, history


def temporal_smooth(data: np.ndarray, sigma: float = 1.0) -> np.ndarray:
    """Damp the frame-to-frame roughness DBA introduces.

    Each reference frame averages whichever take-frames the warp assigned to it,
    and that membership changes abruptly between adjacent frames — so the
    barycenter carries a high-frequency wobble that none of the takes has. It is
    an artefact of discrete alignment, not motion, and measurably so: the
    barycenter's median finger jitter comes out above every take that fed it.

    A narrow Gaussian removes it while leaving the trajectory alone. Edges are
    reflected so the first and last frames, which hold the rest pose, do not
    drift toward the middle of the clip.
    """
    if sigma <= 0:
        return data
    radius = max(1, int(round(3 * sigma)))
    x = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-(x * x) / (2 * sigma * sigma))
    kernel /= kernel.sum()

    padded = np.pad(data, ((radius, radius), (0, 0), (0, 0)), mode="reflect")
    out = np.empty_like(data)
    for j in range(data.shape[1]):
        for c in range(data.shape[2]):
            out[:, j, c] = np.convolve(padded[:, j, c], kernel, mode="valid")
    return out


def enforce_bone_lengths(
    data: np.ndarray,
    joint_names: tuple[str, ...],
    parents: dict[str, str | None],
    lengths: dict[str, float],
) -> np.ndarray:
    """Re-project joints so every bone holds its target length.

    Averaging positions independently does not preserve the skeleton: the mean
    of two elbows bent different ways sits closer to the shoulder than either,
    so forearms shrink on the frames where takes disagree most. Walking the
    hierarchy and restoring each bone's length keeps the direction the average
    chose while making the skeleton rigid again.
    """
    index = {n: i for i, n in enumerate(joint_names)}
    order: list[str] = []
    seen: set[str] = set()

    def visit(name: str) -> None:
        if name in seen:
            return
        parent = parents.get(name)
        if parent:
            visit(parent)
        seen.add(name)
        order.append(name)

    for n in joint_names:
        visit(n)

    out = data.copy()
    for name in order:
        parent = parents.get(name)
        if not parent or name not in lengths:
            continue
        ci, pi = index[name], index[parent]
        vec = out[:, ci, :] - out[:, pi, :]
        norm = np.linalg.norm(vec, axis=1, keepdims=True)
        safe = np.where(norm < 1e-9, 1.0, norm)
        out[:, ci, :] = out[:, pi, :] + vec / safe * lengths[name]
    return out


def median_bone_lengths(
    takes: list[np.ndarray], joint_names: tuple[str, ...], parents: dict[str, str | None]
) -> dict[str, float]:
    """Median length of each bone across every frame of every take."""
    index = {n: i for i, n in enumerate(joint_names)}
    lengths: dict[str, float] = {}
    for name, parent in parents.items():
        if not parent or name not in index or parent not in index:
            continue
        vals = [
            np.linalg.norm(t[:, index[name], :] - t[:, index[parent], :], axis=1) for t in takes
        ]
        lengths[name] = float(np.median(np.concatenate(vals)))
    return lengths
