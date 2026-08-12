"""Validate SMPLest-X NPZ from Phase 2 — checks shapes, joints, finiteness."""
import argparse
import sys
from pathlib import Path
import numpy as np

def main(path: Path):
    data = np.load(path, allow_pickle=False)
    poses = data["poses"]
    trans = data["trans"]
    jc = data["smplx_joint_cam"]
    print(f"poses {poses.shape}, trans {trans.shape}, jc {jc.shape}")
    n = poses.shape[0]
    assert poses.shape == (n,165), f"poses {poses.shape} != ({n},165)"
    assert trans.shape == (n,3), f"trans {trans.shape} != ({n},3)"
    assert jc.ndim==3 and jc.shape[0]==n and jc.shape[2]==3
    assert jc.shape[1] >=55, f"J {jc.shape[1]} <55"
    assert np.isfinite(poses).all()
    assert np.isfinite(trans).all()
    assert np.isfinite(jc).all()
    print("PASS: all checks")
    print(f"J={jc.shape[1]}, N={n}, FPS={float(data['mocap_frame_rate'])}")

if __name__ == "__main__":
    p = Path(sys.argv[1]) if len(sys.argv)>1 else Path("offline/output/smplx/isl_hello_MVI_0029.npz")
    main(p)
