"""SMPLest-X → AMASS-style SMPL-X NPZ exporter (Google Colab, standalone).

PURPOSE
-------
Run SMPLest-X on ONE ISL clip and save the model's OWN output tensors as an
AMASS-compatible NPZ. This does NOT retarget, IK, smooth, interpolate, map bones,
or do any avatar-specific math. It is a pure dumper + validator that sits UPSTREAM
of the Mac motionpipe. Nothing in the Mac production pipeline is imported or
touched.

WHERE THIS RUNS
---------------
Google Colab (T4/CUDA), inside a clone of SMPLCap/SMPLest-X. It is deliberately
NOT wired into offline/motionpipe — it produces a raw NPZ artifact that a later,
separately-reviewed adapter will consume.

OUTPUT NPZ (AMASS SMPL-X layout)
--------------------------------
    poses            float32 [N,165]   see POSE LAYOUT below
    trans            float32 [N,3]     cam_trans (CAMERA FRAME — see note)
    betas            float32 [10 or 16] mean of per-frame smplx_shape
    gender           str "neutral"
    mocap_frame_rate float 25.0
    # extras (not required by the Blender loader, kept for the adapter/debug):
    root_pose, body_pose, lhand_pose, rhand_pose, jaw_pose, expr, betas_per_frame

POSE LAYOUT (165 = the SMPL-X full-pose vector the Blender add-on expects)
    [  0:  3)  root / global orientation   <- smplx_root_pose  [3]
    [  3: 66)  body pose (21 joints * 3)    <- smplx_body_pose  [63]
    [ 66: 69)  jaw                          <- smplx_jaw_pose   [3]
    [ 69: 72)  left eye  = zeros            (SMPLest-X emits no eye pose)
    [ 72: 75)  right eye = zeros
    [ 75:120)  left hand (15 joints * 3)    <- smplx_lhand_pose [45]  FULL axis-angle
    [120:165)  right hand(15 joints * 3)    <- smplx_rhand_pose [45]  FULL axis-angle
Hands are full axis-angle (NOT PCA): 15 joints * 3 = 45 each -> all 30 finger
joints preserved.

TRANSLATION NOTE
    trans = cam_trans is in the CAMERA coordinate frame, so global translation is
    APPROXIMATE (no world/ground solve). Body & hand articulation are unaffected;
    only root world-placement is camera-relative. Documented, not hidden.

SINGLE-PERSON CONTRACT
    ISL clips are single-signer. If the detector finds >1 person in ANY sampled
    frame this script ABORTS (it never silently picks a person). Re-run with a
    tighter crop / detector threshold if that fires.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

# ----------------------------------------------------------------------------
# Layout constants — the only "knowledge" this file encodes.
# ----------------------------------------------------------------------------
N_BODY = 63          # 21 joints * 3
N_HAND = 45          # 15 joints * 3
POSE_DIM = 165
FPS = 25.0
GENDER = "neutral"


def assemble_pose_vector(out: dict) -> np.ndarray:
    """One frame's SMPLest-X `out` dict -> [165] AMASS pose vector.

    `out` values may be torch tensors or numpy; we accept either and squeeze the
    batch dim. Eyes are zero-filled (SMPLest-X does not estimate them).
    """
    def vec(key, n):
        v = out[key]
        v = v.detach().cpu().numpy() if hasattr(v, "detach") else np.asarray(v)
        v = np.asarray(v, dtype=np.float32).reshape(-1)
        if v.shape[0] != n:
            raise ValueError(f"{key}: expected {n} values, got {v.shape[0]}")
        return v

    root = vec("smplx_root_pose", 3)
    body = vec("smplx_body_pose", N_BODY)
    jaw = vec("smplx_jaw_pose", 3)
    lhand = vec("smplx_lhand_pose", N_HAND)
    rhand = vec("smplx_rhand_pose", N_HAND)
    eyes = np.zeros(6, dtype=np.float32)  # left eye [3] + right eye [3]

    pose = np.concatenate([root, body, jaw, eyes, lhand, rhand]).astype(np.float32)
    if pose.shape[0] != POSE_DIM:
        raise ValueError(f"assembled pose is {pose.shape[0]}, expected {POSE_DIM}")
    return pose


def collect_frames(run_frame, n_frames: int):
    """Drive SMPLest-X frame-by-frame and gather tensors.

    `run_frame(i)` is supplied by the Colab integration cell (see __main__). It
    MUST return, for frame i, a tuple:
        (n_persons: int, out: dict|None, cam_trans: (3,) array|None, betas, expr)
    with out=None when n_persons != 1. This keeps SMPLest-X's exact demo/detector
    wiring in the notebook, where it can be adapted to the repo, while the layout
    and validation logic stays here under version control.
    """
    poses, trans, betas_pf, expr_pf, joints = [], [], [], [], []
    root_l, body_l, lh_l, rh_l, jaw_l = [], [], [], [], []
    person_counts, skipped, kept_index = [], [], []

    def _np(out, k):
        v = out[k]
        return (v.detach().cpu().numpy() if hasattr(v, "detach") else np.asarray(v))

    for i in range(n_frames):
        n_persons, out, cam_trans, betas, expr = run_frame(i)
        person_counts.append(n_persons)
        if n_persons == 0:
            skipped.append(i)                      # report + skip; never fabricate a pose
            continue
        if n_persons > 1:
            raise RuntimeError(
                f"frame {i}: {n_persons} people detected. This exporter refuses to "
                f"guess which is the signer. Re-crop/re-threshold and retry."
            )
        kept_index.append(i)
        poses.append(assemble_pose_vector(out))
        trans.append(np.asarray(cam_trans, dtype=np.float32).reshape(3))
        betas_pf.append(np.asarray(betas, dtype=np.float32).reshape(-1))
        expr_pf.append(np.asarray(expr, dtype=np.float32).reshape(-1))
        # REAL model joint positions — NOT reconstructed from rotations. [J,3].
        jc = _np(out, "smplx_joint_cam").astype(np.float32).reshape(-1, 3)
        joints.append(jc)
        root_l.append(_np(out, "smplx_root_pose").reshape(-1)); body_l.append(_np(out, "smplx_body_pose").reshape(-1))
        lh_l.append(_np(out, "smplx_lhand_pose").reshape(-1)); rh_l.append(_np(out, "smplx_rhand_pose").reshape(-1))
        jaw_l.append(_np(out, "smplx_jaw_pose").reshape(-1))

    if not joints:
        raise RuntimeError("no single-person frames were kept — nothing to export")
    j_counts = {j.shape[0] for j in joints}
    if len(j_counts) != 1:
        raise RuntimeError(f"smplx_joint_cam joint count varies across frames: {j_counts}")

    return {
        "person_counts": np.asarray(person_counts, dtype=np.int32),
        "skipped_frames": np.asarray(skipped, dtype=np.int32),
        "kept_index": np.asarray(kept_index, dtype=np.int32),
        "poses": np.stack(poses),
        "trans": np.stack(trans),
        "smplx_joint_cam": np.stack(joints),           # [N,J,3]
        "betas_per_frame": np.stack(betas_pf),
        "expr": np.stack(expr_pf),
        "root_pose": np.stack(root_l), "body_pose": np.stack(body_l),
        "lhand_pose": np.stack(lh_l), "rhand_pose": np.stack(rh_l),
        "jaw_pose": np.stack(jaw_l),
    }


def validate(data: dict, fps: float) -> list[str]:
    """Hard checks. Returns a list of human-readable PASS/FAIL lines; raises on FAIL."""
    poses, trans, jc = data["poses"], data["trans"], data["smplx_joint_cam"]
    n = poses.shape[0]
    checks = []

    def ok(cond, msg):
        checks.append(("PASS" if cond else "FAIL") + " " + msg)
        return cond

    all_ok = True
    all_ok &= ok(n > 0, f"frame_count = {n} (>0)")
    all_ok &= ok(poses.shape == (n, POSE_DIM), f"poses shape {poses.shape} == ({n},165)")
    all_ok &= ok(trans.shape == (n, 3), f"trans shape {trans.shape} == ({n},3)")
    all_ok &= ok(data["lhand_pose"].shape[1] == 45, "left hand = 45 (15 joints)")
    all_ok &= ok(data["rhand_pose"].shape[1] == 45, "right hand = 45 (15 joints)")
    all_ok &= ok(np.isfinite(poses).all(), "poses finite (no NaN/Inf)")
    all_ok &= ok(np.isfinite(trans).all(), "trans finite (no NaN/Inf)")
    all_ok &= ok(jc.ndim == 3 and jc.shape[0] == n and jc.shape[2] == 3,
                 f"smplx_joint_cam shape {jc.shape} == ({n},J,3)")
    all_ok &= ok(np.isfinite(jc).all(), "smplx_joint_cam finite (no NaN/Inf)")
    # SMPL-X core kinematic joints run 0..54 (25 body/face + 15 left hand + 15 right).
    all_ok &= ok(jc.shape[1] >= 55, f"joint tensor J={jc.shape[1]} >= 55 (body+30 finger joints present)")
    # 30 finger joints preserved: both hand blocks present and non-trivially varying
    lh = poses[:, 75:120]; rh = poses[:, 120:165]
    all_ok &= ok(lh.shape[1] == 45 and rh.shape[1] == 45, "165-vector carries both 45-dim hand blocks (30 finger joints)")
    all_ok &= ok(fps > 0, f"mocap_frame_rate = {fps}")
    if not all_ok:
        raise RuntimeError("VALIDATION FAILED:\n  " + "\n  ".join(checks))
    return checks


def save_npz(out_path: Path, data: dict, fps: float) -> None:
    betas = data["betas_per_frame"].mean(axis=0).astype(np.float32)
    np.savez(
        out_path,
        poses=data["poses"].astype(np.float32),
        trans=data["trans"].astype(np.float32),
        smplx_joint_cam=data["smplx_joint_cam"].astype(np.float32),   # [N,J,3] REAL joints
        betas=betas,
        gender=GENDER,
        mocap_frame_rate=np.float32(fps),
        # extras for the downstream adapter / debugging (ignored by Blender loader):
        betas_per_frame=data["betas_per_frame"].astype(np.float32),
        expr=data["expr"].astype(np.float32),
        root_pose=data["root_pose"].astype(np.float32),
        body_pose=data["body_pose"].astype(np.float32),
        lhand_pose=data["lhand_pose"].astype(np.float32),
        rhand_pose=data["rhand_pose"].astype(np.float32),
        jaw_pose=data["jaw_pose"].astype(np.float32),
        person_counts=data["person_counts"],
        skipped_frames=data["skipped_frames"],
        kept_index=data["kept_index"],
    )


# ----------------------------------------------------------------------------
# Colab integration point.
#
# `build_run_frame(video_path)` MUST be implemented in the notebook against the
# actual SMPLest-X demo API of the cloned repo (detector + model.forward). It
# returns (run_frame, n_frames). We keep this a stub on purpose: the layout &
# validation above are the reviewed, version-controlled contract; the repo-
# specific inference wiring stays visible in the notebook cell.
# ----------------------------------------------------------------------------
def build_run_frame(video_path: str, *, ckpt_name: str | None = None,
                    repo_root: str | None = None):
    """Real SMPLest-X inference, mirroring main/inference.py of SMPLCap/SMPLest-X.

    Traced 1:1 from the official repo (verified against main/inference.py,
    main/SMPLest_X.py's test-mode `out` dict, and utils/inference_utils). No API
    names are invented. Runs in Colab where the repo + checkpoint + SMPL-X body
    models are present; CANNOT run on the Mac (no repo/checkpoint/GPU).

    Returns (run_frame, n_frames) where run_frame(i) ->
        (n_persons, out|None, cam_trans|None, betas|None, expr|None).
    Frames are read in order from the video; NO resampling / interpolation.
    """
    import os
    import os.path as osp
    import cv2
    import numpy as _np
    import torch
    import torchvision.transforms as transforms

    # Repo must be importable (main.*, utils.*, human_models.*). In Colab this is
    # the cloned SMPLest-X root; default to it, allow override.
    root = repo_root or os.environ.get("SMPLESTX_ROOT", "/content/SMPLest-X")
    if root not in sys.path:
        sys.path.insert(0, root)

    from ultralytics import YOLO                                  # official detector
    from main.config import Config                                # official config
    from main.base import Tester                                  # official model wrapper
    from utils.data_utils import load_img, process_bbox, generate_patch_image
    from utils.inference_utils import non_max_suppression

    ckpt_name = ckpt_name or os.environ.get("SMPLESTX_CKPT", "smplest_x_h")
    # --- config + model + checkpoint (once), exactly as inference.py does -------
    config_path = osp.join(root, "pretrained_models", ckpt_name, "config_base.py")
    ckpt_path = osp.join(root, "pretrained_models", ckpt_name, f"{ckpt_name}.pth.tar")
    cfg = Config.load_config(config_path)
    cfg.update_config({"model": {"pretrained_model_path": ckpt_path}})
    cfg.prepare_log()
    demoer = Tester(cfg)
    demoer._make_model()
    demoer.model.eval()

    detector = YOLO(osp.join(root, "pretrained_models", "yolov8x.pt"))
    transform = transforms.ToTensor()
    conf = getattr(getattr(cfg, "inference", cfg), "detection", None)
    det_conf = getattr(conf, "conf", 0.5) if conf is not None else 0.5
    in_shape = cfg.model.input_img_shape
    bbox_ratio = getattr(cfg.data, "bbox_ratio", 1.25)

    # --- extract frames in order (no resample), like the demo's frame folder ----
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"could not open video: {video_path}")
    frame_dir = osp.join(osp.dirname(video_path) or ".", "_frames_" + osp.basename(video_path))
    os.makedirs(frame_dir, exist_ok=True)
    paths, idx = [], 0
    while True:
        ok, bgr = cap.read()
        if not ok:
            break
        p = osp.join(frame_dir, f"{idx:06d}.jpg")
        cv2.imwrite(p, bgr)
        paths.append(p)
        idx += 1
    cap.release()

    def run_frame(i):
        original_img = load_img(paths[i])                        # official loader
        h, w = original_img.shape[:2]
        yolo = detector.predict(original_img, device="cuda", classes=0,
                                conf=det_conf, save=False, verbose=False)[0]
        boxes = yolo.boxes.xyxy  # (N,4) tensor
        boxes = non_max_suppression(boxes, 0.5) if len(boxes) else boxes  # official NMS
        n_persons = int(len(boxes))
        if n_persons != 1:
            return (n_persons, None, None, None, None)           # 0 or >1 -> caller decides

        x1, y1, x2, y2 = [float(v) for v in boxes[0]]
        xywh = [x1, y1, x2 - x1, y2 - y1]
        bbox = process_bbox(bbox=xywh, img_width=w, img_height=h,
                            input_img_shape=in_shape, ratio=bbox_ratio)
        img, _, _ = generate_patch_image(cvimg=original_img, bbox=bbox, scale=1.0,
                                         rot=0.0, do_flip=False, out_shape=in_shape)
        img = transform(img.astype(_np.float32)) / 255.0
        img = img.cuda()[None, :, :, :]

        inputs = {"img": img}
        with torch.no_grad():
            out = demoer.model(inputs, {}, {}, "test")           # official call signature
        return (1, out, out["cam_trans"], out["smplx_shape"], out["smplx_expr"])

    return run_frame, len(paths)


def main():
    ap = argparse.ArgumentParser(description="Export SMPLest-X outputs to AMASS SMPL-X NPZ")
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fps", type=float, default=FPS)
    args = ap.parse_args()

    run_frame, n_frames = build_run_frame(args.video)
    data = collect_frames(run_frame, n_frames)
    checks = validate(data, args.fps)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    save_npz(out_path, data, args.fps)

    print(f"\nSaved {out_path}  ({data['poses'].shape[0]} single-person frames kept)")
    print("  " + "\n  ".join(checks))
    pc = data["person_counts"]
    print(f"\nPerson detection: {len(pc)} frames read | "
          f"{int((pc == 1).sum())} kept(1) | {int((pc == 0).sum())} skipped(0) | "
          f"{int((pc > 1).sum())} multi(>1)")
    if data["skipped_frames"].size:
        print(f"  skipped frame indices: {data['skipped_frames'].tolist()}")

    # Establish the ACTUAL joint ordering from the real tensor (do not assume J=55).
    J = data["smplx_joint_cam"].shape[1]
    print(f"\nsmplx_joint_cam J = {J}. index | joint name | region")
    for idx in range(J):
        name, region = _smplx_joint_label(idx, J)
        print(f"  {idx:3d} | {name:<16} | {region}")
    print("  NOTE: trans is CAMERA-FRAME (global root placement is approximate).")


# SMPL-X kinematic-tree names for indices 0..54 (authoritative). Indices >= 55 are
# extended landmarks whose meaning depends on the joint set — labelled 'extended'
# and MUST be confirmed against the config before the adapter trusts them.
_SMPLX_NAMES = [
    "pelvis", "left_hip", "right_hip", "spine1", "left_knee", "right_knee", "spine2",
    "left_ankle", "right_ankle", "spine3", "left_foot", "right_foot", "neck",
    "left_collar", "right_collar", "head", "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow", "left_wrist", "right_wrist", "jaw", "left_eye",
    "right_eye",
    "l_index1", "l_index2", "l_index3", "l_middle1", "l_middle2", "l_middle3",
    "l_pinky1", "l_pinky2", "l_pinky3", "l_ring1", "l_ring2", "l_ring3",
    "l_thumb1", "l_thumb2", "l_thumb3",
    "r_index1", "r_index2", "r_index3", "r_middle1", "r_middle2", "r_middle3",
    "r_pinky1", "r_pinky2", "r_pinky3", "r_ring1", "r_ring2", "r_ring3",
    "r_thumb1", "r_thumb2", "r_thumb3",
]


def _smplx_joint_label(idx: int, J: int):
    if idx < len(_SMPLX_NAMES):
        name = _SMPLX_NAMES[idx]
        if idx <= 11 or idx in (9, 3, 6):
            region = "body/leg/spine"
        elif idx in (12, 13, 14, 15, 22, 23, 24):
            region = "head/neck/face"
        elif 16 <= idx <= 21:
            region = "arm"
        elif 25 <= idx <= 39:
            region = "left hand"
        else:
            region = "right hand"
        return name, region
    return f"ext_{idx}", "extended (confirm vs config — may be fingertip/contour)"


if __name__ == "__main__":
    sys.exit(main())
