"""Validate the SMPL-X -> HumanMotionSequence adapter.

Usage:
    python -m offline.tools.test_smplx_adapter --npz path/to/real.npz     # real data
    python -m offline.tools.test_smplx_adapter                            # schema-only

With --npz it converts a REAL exported SMPL-X NPZ. Without it, it builds a
STRUCTURAL fixture (arange-filled [N,55,3]) purely to exercise the index mapping
and coverage checks — this proves the adapter WIRING, NOT motion correctness. It
never writes a VRMA and never fabricates a "real" NPZ on disk.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np

from offline.motionpipe.smplx_adapter import smplx_npz_to_human_motion, SMPLX


def _synthetic_npz(tmp_path):
    n, J = 4, 55
    # Distinct, finite coordinates per joint so mapping mistakes are visible.
    joints = np.arange(n * J * 3, dtype=np.float32).reshape(n, J, 3)
    np.savez(tmp_path, smplx_joint_cam=joints, mocap_frame_rate=np.float32(25.0),
             poses=np.zeros((n, 165), np.float32), trans=np.zeros((n, 3), np.float32),
             betas=np.zeros(10, np.float32), gender="neutral")
    return tmp_path


def _finite(seq):
    for f in seq.frames:
        for grp in (f.body, f.left_hand, f.right_hand):
            for lm in grp:
                if not all(np.isfinite([lm.x, lm.y, lm.z])):
                    return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--npz", default=None)
    args = ap.parse_args()

    real = args.npz is not None
    if real:
        npz = args.npz
    else:
        import tempfile, os
        npz = os.path.join(tempfile.mkdtemp(), "synthetic.npz")
        _synthetic_npz(npz)

    seq = smplx_npz_to_human_motion(npz, gloss="HELLO", source_video="(test)")
    m = seq.meta

    body_cov = sum(1 for lm in seq.frames[0].body if lm.confidence > 0)
    lh = seq.frames[0].left_hand
    rh = seq.frames[0].right_hand
    lh_measured = sum(1 for lm in lh if lm.confidence > 0)
    rh_measured = sum(1 for lm in rh if lm.confidence > 0)
    tip_idx = {4, 8, 12, 16, 20}
    finger_slots = [i for i in range(21) if i not in {0}]

    print(f"mode                : {'REAL NPZ' if real else 'SCHEMA-ONLY FIXTURE (wiring test)'}")
    print(f"frame_count         : {m.frame_count}")
    print(f"fps                 : {m.fps}")
    print(f"joint groups        : {m.landmark_groups}")
    print(f"body slots measured : {body_cov}/13 expected mapped (excl. head-shared)")
    print(f"left-hand slots     : {len(lh)} (expect 21)   measured(conf>0): {lh_measured}")
    print(f"right-hand slots    : {len(rh)} (expect 21)   measured(conf>0): {rh_measured}")
    print(f"finger joints/hand  : {len(finger_slots)} slots (20)  measured non-tip: "
          f"{sum(1 for i in finger_slots if i not in tip_idx)}")
    print(f"fingertips/hand     : {len(tip_idx)} slots — SYNTHESIZED (conf 0, distal copy)")
    print(f"no NaN/Inf          : {_finite(seq)}")

    ok = (len(lh) == 21 and len(rh) == 21 and m.frame_count > 0 and _finite(seq)
          and lh_measured >= 15 and rh_measured >= 15 and body_cov >= 12)
    print(f"\nWIRING {'PASS' if ok else 'FAIL'}"
          + ("" if real else "  (structural only — end-to-end motion validation "
             "PENDING real SMPLest-X NPZ)"))
    # SMPL-X ordering echo for manual confirmation against the real J:
    print(f"max SMPL-X index used: {max(SMPLX.values())} (needs J >= 55)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
