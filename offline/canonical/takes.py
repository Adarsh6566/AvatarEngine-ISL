"""Loading and quality-screening the takes of one sign.

A "take" is one performance of a sign by one signer, already extracted to a
view-space skeleton stream. The Greetings set holds roughly twenty per sign,
recorded across three sessions with different signers, so the takes vary in
timing, amplitude and body proportion — not just in noise.

Screening happens before averaging because a take whose hands were lost for a
stretch does not contribute a worse average, it contributes a wrong one: the
missing frames sit at whatever the tracker last emitted, and the mean drags
toward that.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# The retargeter drives arms, hands and fingers; torso, head and legs are locked
# upright because MediaPipe's depth for them is unreliable and they carry no
# meaning in ISL. Aligning on joints nobody plays back would let irrelevant
# noise steer the warp, so the signal set matches what is actually rendered.
FINGER_TOKENS = ("Thumb", "Index", "Middle", "Ring", "Little", "Pinky")
ARM_JOINTS = ("lShoulder", "lElbow", "lWrist", "lHand", "rShoulder", "rElbow", "rWrist", "rHand")


@dataclass(frozen=True)
class Take:
    """One performance, as (frames, joints, 3) in view space."""

    name: str
    sign: str
    joint_names: tuple[str, ...]
    data: np.ndarray  # (T, J, 3)
    fps: float
    dropout: float

    @property
    def n_frames(self) -> int:
        return self.data.shape[0]


def signal_indices(joint_names: tuple[str, ...]) -> np.ndarray:
    """Indices of the joints that alignment and scoring should consider."""
    keep = [
        i
        for i, n in enumerate(joint_names)
        if n in ARM_JOINTS or any(tok in n for tok in FINGER_TOKENS)
    ]
    return np.asarray(keep, dtype=int)


def alignment_features(
    data: np.ndarray, joint_names: tuple[str, ...], finger_weight: float = 1.0
) -> np.ndarray:
    """(T, D) features for time-warping: arms in place, fingers relative to the hand.

    Aligning on raw positions lets the arm decide everything. Finger joints are
    absolute too, so all forty of them carry the arm's trajectory and contribute
    it again; the handshape itself, a couple of centimetres of movement against
    half a metre of arm travel, is lost in the sum. Two takes then align by when
    the arm was raised and not by when the hand opened, and averaging under that
    warp blends an open hand into a closed one.

    Subtracting the hand root leaves only articulation, which is enough on its
    own: weight 1.0 measured best on 'pleased', both for how well the template
    represents the takes (+7.1% against the best single take, vs +5.9% aligning
    on raw positions) and for how much of the opening survives (96% of the
    takes' peak fingertip spread, vs 93%). Amplifying further trades score for
    little extra range — the warp starts chasing finger noise, the same noise
    the runtime damps at 0.9.

    Used for ALIGNMENT only; the averaging still runs on raw positions.
    """
    index = {n: i for i, n in enumerate(joint_names)}
    blocks = []

    arms = [index[n] for n in ARM_JOINTS if n in index]
    if arms:
        blocks.append(data[:, arms, :].reshape(data.shape[0], -1))

    for side in ("l", "r"):
        hand = index.get(f"{side}Hand")
        fingers = [
            i
            for i, n in enumerate(joint_names)
            if n.startswith(side) and any(tok in n for tok in FINGER_TOKENS)
        ]
        if hand is None or not fingers:
            continue
        relative = data[:, fingers, :] - data[:, [hand], :]
        blocks.append(relative.reshape(data.shape[0], -1) * finger_weight)

    return np.concatenate(blocks, axis=1) if blocks else data.reshape(data.shape[0], -1)


def _dropout_fraction(data: np.ndarray, joint_names: tuple[str, ...]) -> float:
    """Fraction of frames where a wrist is missing or pinned at the origin.

    MediaPipe emits a joint for every frame whether or not it saw one, so an
    absent hand shows up as a degenerate value rather than a gap. Both hands
    sitting exactly at the root is the signature of a frame with no detection.
    """
    idx = [i for i, n in enumerate(joint_names) if n in ("lWrist", "rWrist")]
    if not idx:
        return 1.0
    wrists = data[:, idx, :]
    degenerate = np.all(np.abs(wrists) < 1e-9, axis=(1, 2))
    nonfinite = ~np.all(np.isfinite(wrists), axis=(1, 2))
    return float(np.mean(degenerate | nonfinite))


def load_take(path: Path, sign: str) -> Take:
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    meta = payload["meta"]
    names = tuple(j["name"] for j in meta["joints"])
    frames = payload["frames"]

    data = np.zeros((len(frames), len(names), 3), dtype=np.float64)
    for t, frame in enumerate(frames):
        joints = frame["joints"]
        for j, name in enumerate(names):
            v = joints.get(name)
            if isinstance(v, (list, tuple)) and len(v) >= 3:
                data[t, j] = v[:3]
    data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)

    return Take(
        name=path.stem,
        sign=sign,
        joint_names=names,
        data=data,
        fps=float(meta.get("fps") or 25.0),
        dropout=_dropout_fraction(data, names),
    )


def load_sign(cache_dir: Path, sign: str, max_dropout: float = 0.02) -> tuple[list[Take], list[Take]]:
    """Load every take of a sign, split into (kept, rejected)."""
    d = cache_dir / sign
    if not d.exists():
        return [], []
    takes = [load_take(p, sign) for p in sorted(d.glob("*.json"))]

    # Joint layout is fixed by the schema, but guard anyway: a take with a
    # different layout cannot be averaged elementwise with the rest.
    if takes:
        layout = takes[0].joint_names
        takes = [t for t in takes if t.joint_names == layout]

    kept = [t for t in takes if t.dropout <= max_dropout]
    rejected = [t for t in takes if t.dropout > max_dropout]
    return kept, rejected
