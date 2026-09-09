"""Repair the hand pose on frames where the tracker's palm solution jumped.

MediaPipe's hand landmarker solves each frame independently, and a hand seen
edge-on or through motion blur is genuinely ambiguous: palm-toward and
palm-away fit the same silhouette. The tracker picks one per frame and
oscillates between them, so the palm can invert between consecutive frames.
Measured across 63 takes of the Pronouns set, 4.5% of frames turn the hand more
than 90 degrees in a single 1/25s step, and the worst reaches 179.6 degrees — a
flip, not a movement.

A wrist cannot do that. Pronation and supination peak near 1000 deg/s even in
fast athletic movement, so 900 deg/s is used here as the ceiling on what
capture is allowed to claim. Everything under it passes through untouched; only
frames above it are treated as a failed solve and rebuilt.

The repair is deliberately narrow. The hand's POSITION is left exactly as
captured, because it is carried by the arm and the body pose estimate is the
reliable channel. What gets rebuilt is the hand's ORIENTATION and the direction
of each finger bone within the hand's own frame — the two things that come from
the ambiguous solve. Both are interpolated across the bad frames from the
nearest frames on either side that the rate test accepts, and both are
interpolated as rotations, never as positions.

Why this and not more smoothing: the pipeline already despikes with a 3-frame
median and smooths with a Gaussian, and the artefact survives both. A median
cannot fix a flip that persists for two frames, and a Gaussian averages the
flipped pose into its neighbours instead of discarding it — widening the window
spreads the error rather than removing it. The rate test is the only stage that
asks whether a frame is physically possible at all.
"""

from __future__ import annotations

import numpy as np

FINGER_TOKENS = ("Thumb", "Index", "Middle", "Ring", "Little", "Pinky")

# Ceiling on wrist angular speed. See module docstring.
MAX_DEG_PER_S = 900.0

# Ceiling on how fast one finger bone may swing relative to its own hand. The
# palm's motion is already divided out at this point, so this is articulation
# alone — curling and straightening. Rapid finger tapping tops out near 800
# deg/s, and signing is not tapping, so 700 is generous.
#
# This is a separate test from the wrist because the two fail independently: a
# frame can hold the palm perfectly steady and still snap one finger 178
# degrees, which is what the first version of this module let through.
MAX_FINGER_DEG_PER_S = 700.0

# A take whose hand could not be solved for most of its frames is not a noisier
# input, it is a wrong one — the same reasoning the dropout screen already
# applies to missing wrists. Past this fraction the repair would be inventing
# the majority of the performance, so the take is rejected instead.
MAX_UNSOLVED_FRACTION = 0.5


def _hand_frames(data: np.ndarray, index: dict[str, int], side: str):
    """Per-frame orthonormal hand basis, plus how well-conditioned each one is.

    Primary axis is hand->middle knuckle, the same direction the retargeter
    drives the wrist bone along. Secondary is index->little across the knuckle
    fan, the widest baseline the palm offers and so the least noise-sensitive
    thing available to fix roll against.
    """
    o = data[:, index[f"{side}Hand"]]
    x = data[:, index[f"{side}Middle1"]] - o
    across = data[:, index[f"{side}Index1"]] - data[:, index[f"{side}Pinky1"]]

    xn = x / (np.linalg.norm(x, axis=1, keepdims=True) + 1e-12)
    z = np.cross(xn, across)
    zmag = np.linalg.norm(z, axis=1)
    zn = z / (zmag[:, None] + 1e-12)
    yn = np.cross(zn, xn)
    R = np.stack([xn, yn, zn], axis=2)  # columns are the basis vectors

    # sin of the angle between the two axes: near zero means the fan collapsed
    # to a line and roll is not observable at all this frame. `z` is built from
    # the ALREADY NORMALISED primary, so only `across` divides out here —
    # dividing by |x| as well silently scaled this by 1/|x| (about 8x at these
    # hand sizes) and the gate never fired.
    cond = zmag / (np.linalg.norm(across, axis=1) + 1e-12)
    return R, o, cond


def _to_quat(R: np.ndarray) -> np.ndarray:
    """Rotation matrices (T,3,3) -> unit quaternions (T,4) as (w,x,y,z).

    Shepperd's method: take the branch with the largest denominator, so the
    division never happens near zero.
    """
    T = R.shape[0]
    q = np.empty((T, 4))
    m00, m11, m22 = R[:, 0, 0], R[:, 1, 1], R[:, 2, 2]
    tr = m00 + m11 + m22
    for t in range(T):
        if tr[t] > 0:
            s = np.sqrt(tr[t] + 1.0) * 2
            q[t] = [
                0.25 * s,
                (R[t, 2, 1] - R[t, 1, 2]) / s,
                (R[t, 0, 2] - R[t, 2, 0]) / s,
                (R[t, 1, 0] - R[t, 0, 1]) / s,
            ]
        elif m00[t] > m11[t] and m00[t] > m22[t]:
            s = np.sqrt(1.0 + m00[t] - m11[t] - m22[t]) * 2
            q[t] = [
                (R[t, 2, 1] - R[t, 1, 2]) / s,
                0.25 * s,
                (R[t, 0, 1] + R[t, 1, 0]) / s,
                (R[t, 0, 2] + R[t, 2, 0]) / s,
            ]
        elif m11[t] > m22[t]:
            s = np.sqrt(1.0 + m11[t] - m00[t] - m22[t]) * 2
            q[t] = [
                (R[t, 0, 2] - R[t, 2, 0]) / s,
                (R[t, 0, 1] + R[t, 1, 0]) / s,
                0.25 * s,
                (R[t, 1, 2] + R[t, 2, 1]) / s,
            ]
        else:
            s = np.sqrt(1.0 + m22[t] - m00[t] - m11[t]) * 2
            q[t] = [
                (R[t, 1, 0] - R[t, 0, 1]) / s,
                (R[t, 0, 2] + R[t, 2, 0]) / s,
                (R[t, 1, 2] + R[t, 2, 1]) / s,
                0.25 * s,
            ]
    return q / (np.linalg.norm(q, axis=1, keepdims=True) + 1e-12)


def _to_mat(q: np.ndarray) -> np.ndarray:
    w, x, y, z = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    return np.stack(
        [
            np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)], axis=1),
            np.stack([2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)], axis=1),
            np.stack([2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], axis=1),
        ],
        axis=1,
    )


def _slerp(q0: np.ndarray, q1: np.ndarray, u: float) -> np.ndarray:
    """Shortest-arc interpolation between two unit quaternions."""
    d = float(np.dot(q0, q1))
    if d < 0.0:  # same rotation, opposite sign: take the short way round
        q1, d = -q1, -d
    if d > 0.9995:
        q = q0 + u * (q1 - q0)
        return q / (np.linalg.norm(q) + 1e-12)
    theta = np.arccos(np.clip(d, -1.0, 1.0))
    s = np.sin(theta)
    return (np.sin((1 - u) * theta) / s) * q0 + (np.sin(u * theta) / s) * q1


def _angle_between(qa: np.ndarray, qb: np.ndarray) -> float:
    d = abs(float(np.dot(qa, qb)))
    return float(np.degrees(2.0 * np.arccos(np.clip(d, -1.0, 1.0))))


def _slerp_vec(a: np.ndarray, b: np.ndarray, u: float) -> np.ndarray:
    """Interpolate between two unit vectors along the sphere."""
    d = float(np.clip(np.dot(a, b), -1.0, 1.0))
    if d > 0.9995 or d < -0.9995:
        v = a + u * (b - a)
        n = np.linalg.norm(v)
        return a if n < 1e-9 else v / n
    theta = np.arccos(d)
    s = np.sin(theta)
    return (np.sin((1 - u) * theta) / s) * a + (np.sin(u * theta) / s) * b


def _hand_chain(
    joint_names: tuple[str, ...], parents: dict[str, str | None], side: str
) -> list[tuple[int, int]]:
    """(parent, child) index pairs for the finger bones of one hand, root first.

    Ordered so a walk can place each child after its parent already has a
    position.
    """
    hand = f"{side}Hand"
    fingers = {
        n
        for n in joint_names
        if n.startswith(side) and any(t in n for t in FINGER_TOKENS)
    }
    index = {n: i for i, n in enumerate(joint_names)}
    placed = {hand}
    chain: list[tuple[int, int]] = []
    remaining = set(fingers)
    while remaining:
        progressed = False
        for n in sorted(remaining):
            p = parents.get(n)
            if p in placed:
                chain.append((index[p], index[n]))
                placed.add(n)
                remaining.discard(n)
                progressed = True
        if not progressed:  # a joint whose parent is outside the hand
            break
    return chain


def stabilize_hands(
    data: np.ndarray,
    joint_names: tuple[str, ...],
    parents: dict[str, str | None],
    fps: float,
    max_deg_per_s: float = MAX_DEG_PER_S,
    min_cond: float = 0.15,
) -> tuple[np.ndarray, dict]:
    """Rebuild hand orientation and handshape on physically impossible frames.

    The handshape is carried as one unit direction per finger bone in the hand's
    own frame, never as positions. Interpolating positions is what the rest of
    this pipeline already knows not to do — the mean of two differently-bent
    joints sits closer to its parent than either — and it bites hardest here:
    lerping a repaired frame between two trusted ones collapsed a bone by 82%.
    Directions interpolate on the sphere and lengths are re-applied from the
    median, so bone length is exact by construction and the skeleton needs no
    correction afterwards.

    That matters for ordering too. This has to be the LAST stage: running
    `enforce_bone_lengths` after it rescales each knuckle independently from the
    hand, which swings the index->little vector the palm's roll is measured
    against and put the flip straight back (33 deg/frame -> 171).

    Returns (repaired copy, per-side report). The input is not modified.
    """
    index = {n: i for i, n in enumerate(joint_names)}
    out = data.copy()
    report: dict[str, dict] = {}

    per_frame_limit = max_deg_per_s / max(fps, 1e-6)

    for side in ("l", "r"):
        need = [f"{side}Hand", f"{side}Middle1", f"{side}Index1", f"{side}Pinky1"]
        if not all(n in index for n in need):
            continue
        chain = _hand_chain(joint_names, parents, side)
        if not chain:
            continue

        R, origin, cond = _hand_frames(data, index, side)
        q = _to_quat(R)
        T = len(q)

        # Each finger bone as a unit direction in the hand's own frame, with the
        # arm and the palm's orientation both divided out, plus its length.
        seg = np.stack([data[:, c, :] - data[:, p, :] for p, c in chain], axis=1)
        length = np.linalg.norm(seg, axis=2)
        dirs = np.einsum("tji,tkj->tki", R, seg / (length[:, :, None] + 1e-12))

        # A frame where the tracker saw no hand is not merely noisy: MediaPipe
        # emits a joint whether or not it found one, so an undetected hand comes
        # back as every finger collapsed onto the wrist. 10.5% of all frames are
        # like this, and a collapsed bone has no direction at all — normalising
        # it yields NaN or an arbitrary axis. Such a frame can never be trusted
        # and, more importantly, can never be an endpoint to interpolate from.
        usable = np.isfinite(q).all(axis=1) & (cond >= min_cond)
        usable &= (length > 1e-6).all(axis=1)
        if not usable.any():
            report[side] = {
                "frames": T, "repaired": T, "fraction": 1.0,
                "runs": 1, "longest_run": T, "finger_fraction": 1.0,
            }
            continue

        # Forward trust walk, seeded at the first USABLE frame rather than at
        # frame 0. 15% of takes open on a collapsed hand, and anchoring the walk
        # there measured every later frame against a pose that does not exist.
        trusted = np.zeros(T, dtype=bool)
        first = int(np.flatnonzero(usable)[0])
        trusted[first] = True
        last = first
        for t in range(first + 1, T):
            gap = t - last
            if usable[t] and _angle_between(q[last], q[t]) <= per_frame_limit * gap:
                trusted[t] = True
                last = t

        good = np.flatnonzero(trusted)
        runs: list[int] = []
        # Anything before the seed has nothing earlier to come from: hold it.
        if first > 0:
            runs.append(first)
            for t in range(first):
                q[t] = q[first]
                dirs[t] = dirs[first]
        for a, b in zip(good[:-1], good[1:]):
            if b - a > 1:
                runs.append(int(b - a - 1))
                for t in range(a + 1, b):
                    u = (t - a) / (b - a)
                    q[t] = _slerp(q[a], q[b], u)
                    for k in range(len(chain)):
                        dirs[t, k] = _slerp_vec(dirs[a, k], dirs[b, k], u)
        # A bad tail has nothing to interpolate toward: hold the last good pose.
        tail = T - 1 - int(good[-1])
        if tail > 0:
            runs.append(tail)
            for t in range(int(good[-1]) + 1, T):
                q[t] = q[good[-1]]
                dirs[t] = dirs[good[-1]]

        # Now the fingers, one bone at a time and independently of the wrist.
        # Stabilising the palm says nothing about articulation: with the hand
        # frame already divided out, single bones were still measured snapping
        # 178 degrees between frames, which is what reads as fingers moving on
        # their own and crossing into each other.
        finger_limit = MAX_FINGER_DEG_PER_S / max(fps, 1e-6)
        finger_fixed = 0
        for k in range(len(chain)):
            # Seeded on the same usable mask as the wrist, for the same reason:
            # a collapsed bone has no direction to anchor against.
            ok = np.zeros(T, dtype=bool)
            ok[first] = True
            anchor = first
            for t in range(first + 1, T):
                d = float(np.clip(np.dot(dirs[anchor, k], dirs[t, k]), -1.0, 1.0))
                if usable[t] and np.degrees(np.arccos(d)) <= finger_limit * (t - anchor):
                    ok[t] = True
                    anchor = t
            fine = np.flatnonzero(ok)
            finger_fixed += int(T - ok.sum())
            for a, b in zip(fine[:-1], fine[1:]):
                for t in range(a + 1, b):
                    dirs[t, k] = _slerp_vec(dirs[a, k], dirs[b, k], (t - a) / (b - a))
            for t in range(int(fine[-1]) + 1, T):
                dirs[t, k] = dirs[fine[-1], k]
            for t in range(first):
                dirs[t, k] = dirs[first, k]

        # Rebuild the hand: walk the chain out from the wrist, each bone laid
        # along its repaired direction at the length the takes agree on.
        stable_len = np.median(length[good], axis=0)
        world = np.einsum("tij,tkj->tki", _to_mat(q), dirs) * stable_len[None, :, None]
        for k, (p, c) in enumerate(chain):
            out[:, c, :] = out[:, p, :] + world[:, k, :]

        report[side] = {
            "frames": T,
            "repaired": int(T - trusted.sum()),
            "fraction": float(1.0 - trusted.mean()),
            "runs": len(runs),
            "longest_run": max(runs) if runs else 0,
            "finger_fraction": float(finger_fixed / max(T * len(chain), 1)),
        }

    return out, report


def blend_hands(
    members: np.ndarray,
    base: np.ndarray,
    joint_names: tuple[str, ...],
    parents: dict[str, str | None],
    min_cond: float = 0.15,
) -> np.ndarray:
    """Re-average the hands of one barycenter frame as rotations, not positions.

    `members` are the source frames the warp mapped onto this reference frame;
    `base` is the positional trimmed mean already computed for it. Everything
    outside the hands is left exactly as `base` has it.

    Averaging finger POSITIONS folds fingers, for the same reason the pipeline
    already restores bone lengths after averaging: the mean of two differently
    bent joints sits closer to its parent than either. Bone-length enforcement
    cannot see it, because it fixes each bone's length while leaving the chain's
    joint angles averaged — every bone the right length, the whole finger curled
    tighter than any take performed. Measured on `they`: the takes hold the hand
    at 0.84 / 0.74 / 0.84 / 0.88 straightness across the four fingers and the
    positional mean returned 0.96 / 0.70 / 0.97 / 0.98, three fingers pulled
    straight and one left bent — not a handshape anyone signed. The index also
    reached 0.15 somewhere in the clip, curled far tighter than the tightest
    take at 0.55.

    Averaging the hand's orientation and each bone's direction instead keeps the
    result on the manifold of poses a hand can actually hold.
    """
    index = {n: i for i, n in enumerate(joint_names)}
    out = base.copy()

    for side in ("l", "r"):
        need = [f"{side}Hand", f"{side}Middle1", f"{side}Index1", f"{side}Pinky1"]
        if not all(n in index for n in need):
            continue
        chain = _hand_chain(joint_names, parents, side)
        if not chain:
            continue

        R, _, cond = _hand_frames(members, index, side)
        seg = np.stack([members[:, c, :] - members[:, p, :] for p, c in chain], axis=1)
        length = np.linalg.norm(seg, axis=2)
        ok = (cond >= min_cond) & (length > 1e-6).all(axis=1) & np.isfinite(R).all(axis=(1, 2))
        if ok.sum() < 2:
            continue

        q = _to_quat(R[ok])
        # Quaternions double-cover rotations, so align every sign to the first
        # before averaging or opposite-signed pairs cancel to nothing.
        q = q * np.sign(q @ q[0])[:, None]
        qm = q.mean(axis=0)
        qm /= np.linalg.norm(qm) + 1e-12

        dirs = np.einsum("tji,tkj->tki", R[ok], seg[ok] / (length[ok][:, :, None] + 1e-12))
        dm = dirs.mean(axis=0)
        dm /= np.linalg.norm(dm, axis=1, keepdims=True) + 1e-12

        world = (_to_mat(qm[None])[0] @ dm.T).T * np.median(length[ok], axis=0)[:, None]
        for k, (p, c) in enumerate(chain):
            out[c] = out[p] + world[k]

    return out


def unsolved_fraction(
    data: np.ndarray,
    joint_names: tuple[str, ...],
    parents: dict[str, str | None],
    fps: float,
) -> float:
    """Fraction of frames whose hand orientation could not be solved.

    The screening counterpart to `stabilize_hands`: same test, no repair. High
    values mark the takes where the tracker never held a stable palm.
    """
    _, report = stabilize_hands(data, joint_names, parents, fps)
    return max((v["fraction"] for v in report.values()), default=0.0)
