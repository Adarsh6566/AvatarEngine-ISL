"""
MediaPipe 2.5D extractor — cheap-3D via world landmarks.

Tries mediapipe-tasks vision first (Python 3.13 friendly), falls back to
legacy mediapipe solutions, falls back to dummy sinusoid if nothing installed.

Both "image" (Y-down, pixels normalized 0..1) and "world" (meters, Y-up-ish)
are supported; world is true 3D cheap without SMPL weights.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import List

from .base import Extractor, Space
from .schemas import CANONICAL_JOINTS, JointSpec, SkeletonFrame, SkeletonMeta, SkeletonStreamDict

try:
    from .tracker import assign_hands, maybe_swap_wrists
except ImportError:
    from tracker import assign_hands, maybe_swap_wrists  # type: ignore

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore
    np = None  # type: ignore


# ---------------------------------------------------------------------------
# Dummy fallback — keeps the server working without any heavy dep installed.
# Generates a plausible signing-like motion (hands oscillating).
# ---------------------------------------------------------------------------


def _dummy_stream(video_path: Path, fps: float, frame_count: int, space: Space) -> SkeletonStreamDict:
    n = frame_count if frame_count > 0 else 75  # ~2.5s @30
    frames: List[SkeletonFrame] = []
    for i in range(n):
        t = i / fps
        # hips fixed at origin for view-space friendliness after normalize
        joints = {}
        for j in CANONICAL_JOINTS:
            joints[j.name] = None  # fill below

        # torso static
        joints["hips"] = (0, 0, 0, 1.0)
        joints["spine"] = (0, 0.18, 0, 1.0)
        joints["chest"] = (0, 0.38, 0, 1.0)
        joints["neck"] = (0, 0.58, 0, 1.0)
        joints["head"] = (0, 0.78, 0, 1.0)
        # legs static
        joints["lHip"] = (-0.11, -0.02, 0, 1.0)
        joints["rHip"] = (0.11, -0.02, 0, 1.0)
        joints["lKnee"] = (-0.11, -0.45, 0.04, 1.0)
        joints["rKnee"] = (0.11, -0.45, 0.04, 1.0)
        joints["lAnkle"] = (-0.11, -0.88, 0, 1.0)
        joints["rAnkle"] = (0.11, -0.88, 0, 1.0)
        joints["lFoot"] = (-0.11, -0.95, 0.08, 1.0)
        joints["rFoot"] = (0.11, -0.95, 0.08, 1.0)

        # arms: simple harmonic motion mimicking sign (hands cross / wave)
        phase = t * 2.2
        depth = 0.15 if space == "world" else 0.0  # world has z, image flat
        # left arm
        lx = -0.28 + 0.12 * math.sin(phase)
        ly = 0.32 + 0.10 * math.cos(phase * 1.3)
        lz = depth * math.sin(phase * 0.9)
        joints["lShoulder"] = (-0.19, 0.48, 0, 1.0)
        joints["lElbow"] = (lx - 0.08, ly - 0.10, lz, 0.98)
        joints["lWrist"] = (lx, ly - 0.18, lz + 0.05, 0.97)
        joints["lHand"] = (lx + 0.02, ly - 0.22, lz + 0.07, 0.96)
        joints["lThumb1"] = (lx + 0.05, ly - 0.20, lz + 0.08, 0.9)
        joints["lThumb2"] = (lx + 0.07, ly - 0.18, lz + 0.09, 0.9)
        joints["lIndex1"] = (lx + 0.04, ly - 0.25, lz + 0.10, 0.9)
        joints["lIndex2"] = (lx + 0.06, ly - 0.28, lz + 0.11, 0.9)
        joints["lMiddle1"] = (lx + 0.02, ly - 0.26, lz + 0.10, 0.9)
        joints["lMiddle2"] = (lx + 0.03, ly - 0.29, lz + 0.11, 0.9)
        joints["lRing1"] = (lx + 0.00, ly - 0.25, lz + 0.09, 0.9)
        joints["lRing2"] = (lx + 0.01, ly - 0.27, lz + 0.10, 0.9)
        joints["lPinky1"] = (lx - 0.02, ly - 0.23, lz + 0.08, 0.9)
        joints["lPinky2"] = (lx - 0.03, ly - 0.25, lz + 0.09, 0.9)
        # right arm — opposite phase
        rx = 0.28 + 0.12 * math.sin(phase + math.pi)
        ry = 0.32 + 0.10 * math.cos((phase + math.pi) * 1.3)
        rz = depth * math.sin(phase + math.pi * 0.9)
        joints["rShoulder"] = (0.19, 0.48, 0, 1.0)
        joints["rElbow"] = (rx + 0.08, ry - 0.10, rz, 0.98)
        joints["rWrist"] = (rx, ry - 0.18, rz + 0.05, 0.97)
        joints["rHand"] = (rx - 0.02, ry - 0.22, rz + 0.07, 0.96)
        joints["rThumb1"] = (rx - 0.05, ry - 0.20, rz + 0.08, 0.9)
        joints["rThumb2"] = (rx - 0.07, ry - 0.18, rz + 0.09, 0.9)
        joints["rIndex1"] = (rx - 0.04, ry - 0.25, rz + 0.10, 0.9)
        joints["rIndex2"] = (rx - 0.06, ry - 0.28, rz + 0.11, 0.9)
        joints["rMiddle1"] = (rx - 0.02, ry - 0.26, rz + 0.10, 0.9)
        joints["rMiddle2"] = (rx - 0.03, ry - 0.29, rz + 0.11, 0.9)
        joints["rRing1"] = (rx - 0.00, ry - 0.25, rz + 0.09, 0.9)
        joints["rRing2"] = (rx - 0.01, ry - 0.27, rz + 0.10, 0.9)
        joints["rPinky1"] = (rx + 0.02, ry - 0.23, rz + 0.08, 0.9)
        joints["rPinky2"] = (rx + 0.03, ry - 0.25, rz + 0.09, 0.9)

        # if image space, emulate Y-down image coords (will be flipped by normalize)
        if space == "image":
            for k, v in list(joints.items()):
                if v is None:
                    continue
                x, y, z, c = v
                # map view-space ~[-0.5..0.5] to [0..640] Y-down — normalize will undo
                joints[k] = (320 + x * 200, 320 - y * 200, z * 200, c)  # type: ignore

        frames.append(SkeletonFrame(index=i, timestamp=i / fps, joints=joints))

    # dummy is synthetic Y-up for world (so after normalize it ends up upright); keep label consistent with its generation
    space_label = "image (Y down, pixels)" if space == "image" else "world (Y up, meters, synthetic)"
    meta = SkeletonMeta(
        schema="source_skeleton.v1",
        space=space_label,
        fps=fps,
        frameCount=len(frames),
        duration=len(frames) / fps if fps else 0,
        joints=CANONICAL_JOINTS,
        source_video=str(video_path.name),
        estimator="dummy (no mediapipe installed)",
        coordinate_space=space_label,
    )
    return SkeletonStreamDict(meta=meta, frames=frames)


# ---------------------------------------------------------------------------
# Real MediaPipe path — best-effort; if any import fails we return dummy.
# ---------------------------------------------------------------------------


def _try_mediapipe_tasks_extract(video_path: Path, space: Space, fps: float) -> SkeletonStreamDict | None:
    """Real tasks extraction using PoseLandmarker + HandLandmarker (mediapipe 0.10 tasks).

    Downloads .task bundles on first run to pipeline/.models. Returns None only if
    mediapipe not installed or download fails — otherwise returns a stream even if
    every frame has no detection (no fallback to dummy; dummy is caller's decision).
    """
    try:
        import mediapipe as mp  # type: ignore
        from mediapipe.tasks.python import vision  # type: ignore
        from mediapipe.tasks.python.vision.pose_landmarker import PoseLandmarker  # type: ignore
        from mediapipe.tasks.python.vision.hand_landmarker import HandLandmarker  # type: ignore
    except Exception as e:
        print(f"[mediapipe tasks] import failed: {e}")
        return None

    if cv2 is None:
        print("[mediapipe tasks] cv2 not available")
        return None

    # --- ensure model files ---
    models_dir = Path(__file__).parent.parent / ".models"
    models_dir.mkdir(parents=True, exist_ok=True)
    pose_path = models_dir / "pose_landmarker_lite.task"
    hand_path = models_dir / "hand_landmarker.task"
    pose_url = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
    hand_url = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"

    def ensure_model(path: Path, url: str) -> bool:
        if path.exists() and path.stat().st_size > 1024 * 100:
            return True
        print(f"[mediapipe] downloading {path.name} ...")
        try:
            import urllib.request
            urllib.request.urlretrieve(url, str(path))
            print(f"[mediapipe] saved {path} ({path.stat().st_size} bytes)")
            return True
        except Exception as e:
            print(f"[mediapipe] download failed for {url}: {e}")
            return False

    if not ensure_model(pose_path, pose_url):
        return None
    # hand model optional — pose still works without it
    has_hand = ensure_model(hand_path, hand_url)

    # --- create landmarkers ---
    try:
        from mediapipe.tasks.python.core.base_options import BaseOptions  # type: ignore

        pose_options = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(pose_path)),
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=0.3,
            min_pose_presence_confidence=0.3,
            min_tracking_confidence=0.3,
            output_segmentation_masks=False,
        )
        pose_landmarker = PoseLandmarker.create_from_options(pose_options)
        hand_landmarker = None
        if has_hand:
            try:
                hand_options = vision.HandLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=str(hand_path)),
                    running_mode=vision.RunningMode.IMAGE,
                    num_hands=2,
                    min_hand_detection_confidence=0.3,
                    min_hand_presence_confidence=0.3,
                    min_tracking_confidence=0.3,
                )
                hand_landmarker = HandLandmarker.create_from_options(hand_options)
            except Exception as e:
                print(f"[mediapipe] hand landmarker create failed: {e}")
                hand_landmarker = None
    except Exception as e:
        print(f"[mediapipe] landmarker creation failed: {e}")
        return None

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"[mediapipe] could not open video {video_path}")
        try:
            pose_landmarker.close()
            if hand_landmarker:
                hand_landmarker.close()
        except Exception:
            pass
        return None

    frames: List[SkeletonFrame] = []
    idx = 0
    detected_frames = 0
    # temporal tracker state for hands/wrists
    prev_lHand = None
    prev_rHand = None
    prev_lWrist = None
    prev_rWrist = None
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        joints = {j.name: None for j in CANONICAL_JOINTS}
        try:
            pose_res = pose_landmarker.detect(mp_image)
            pose_lms = None
            pose_world_lms = None
            if pose_res.pose_landmarks:
                pose_lms = pose_res.pose_landmarks[0]
            if hasattr(pose_res, "pose_world_landmarks") and pose_res.pose_world_landmarks:
                pose_world_lms = pose_res.pose_world_landmarks[0]

            # choose which to map — with visibility threshold to avoid hallucinated lower body when cropped
            VIS_THRESH = 0.4
            if space == "world" and pose_world_lms:
                LMS = pose_world_lms  # list of Landmark with x,y,z,visibility

                def wpt(i):
                    p = LMS[i]
                    vis = float(getattr(p, "visibility", 1.0))
                    if vis < VIS_THRESH:
                        return None
                    return (float(p.x), float(p.y), float(p.z), vis)

                if len(LMS) >= 33:
                    # only set if visible — prevents jail-shaped hallucinated legs on upper-body crop
                    for k, idx_lm in [("head",0),("lShoulder",11),("rShoulder",12),("lElbow",13),("rElbow",14),("lWrist",15),("rWrist",16),("lHip",23),("rHip",24),("lKnee",25),("rKnee",26),("lAnkle",27),("rAnkle",28)]:
                        v = wpt(idx_lm)
                        if v is not None:
                            joints[k] = v
                    # derived torso only if both sides visible
                    lh, rh = joints.get("lHip"), joints.get("rHip")
                    ls, rs = joints.get("lShoulder"), joints.get("rShoulder")
                    if lh and rh and lh[3] >= VIS_THRESH and rh[3] >= VIS_THRESH:
                        joints["hips"] = ((lh[0] + rh[0]) / 2, (lh[1] + rh[1]) / 2, (lh[2] + rh[2]) / 2, 1.0)
                    elif lh and lh[3] >= VIS_THRESH:
                        joints["hips"] = lh
                    elif rh and rh[3] >= VIS_THRESH:
                        joints["hips"] = rh
                    if ls and rs:
                        joints["chest"] = ((ls[0] + rs[0]) / 2, (ls[1] + rs[1]) / 2, (ls[2] + rs[2]) / 2, 1.0)
                    elif ls:
                        joints["chest"] = ls
                    elif rs:
                        joints["chest"] = rs
                    if joints.get("hips") and joints.get("chest"):
                        hh, ch = joints["hips"], joints["chest"]  # type: ignore
                        joints["spine"] = ((hh[0] + ch[0]) / 2, (hh[1] + ch[1]) / 2, (hh[2] + ch[2]) / 2, 1.0)
                    if joints.get("chest") and joints.get("head"):
                        ch, hd = joints["chest"], joints["head"]  # type: ignore
                        joints["neck"] = ((ch[0] + hd[0]) / 2, (ch[1] + hd[1]) / 2, (ch[2] + hd[2]) / 2, 1.0)
                    # count detection if we got at least shoulders+hips or head
                    if joints.get("lShoulder") or joints.get("rShoulder") or joints.get("head"):
                        detected_frames += 1
            elif pose_lms:
                LMS = pose_lms

                def ipt(i):
                    p = LMS[i]
                    vis = float(getattr(p, "visibility", 1.0))
                    if vis < VIS_THRESH:
                        return None
                    return (float(p.x) * w, float(p.y) * h, float(p.z) * w, vis)

                if len(LMS) >= 33:
                    for k, idx_lm in [("head",0),("lShoulder",11),("rShoulder",12),("lElbow",13),("rElbow",14),("lWrist",15),("rWrist",16),("lHip",23),("rHip",24),("lKnee",25),("rKnee",26),("lAnkle",27),("rAnkle",28)]:
                        v = ipt(idx_lm)
                        if v is not None:
                            joints[k] = v
                    lh, rh = joints.get("lHip"), joints.get("rHip")
                    ls, rs = joints.get("lShoulder"), joints.get("rShoulder")
                    if lh and rh:
                        joints["hips"] = ((lh[0] + rh[0]) / 2, (lh[1] + rh[1]) / 2, (lh[2] + rh[2]) / 2, 1.0)
                    elif lh:
                        joints["hips"] = lh
                    elif rh:
                        joints["hips"] = rh
                    if ls and rs:
                        joints["chest"] = ((ls[0] + rs[0]) / 2, (ls[1] + rs[1]) / 2, (ls[2] + rs[2]) / 2, 1.0)
                    elif ls:
                        joints["chest"] = ls
                    elif rs:
                        joints["chest"] = rs
                    if joints.get("hips") and joints.get("chest"):
                        hh, ch = joints["hips"], joints["chest"]  # type: ignore
                        joints["spine"] = ((hh[0] + ch[0]) / 2, (hh[1] + ch[1]) / 2, (hh[2] + ch[2]) / 2, 1.0)
                    if joints.get("chest") and joints.get("head"):
                        ch, hd = joints["chest"], joints["head"]  # type: ignore
                        joints["neck"] = ((ch[0] + hd[0]) / 2, (ch[1] + hd[1]) / 2, (ch[2] + hd[2]) / 2, 1.0)
                    if joints.get("lShoulder") or joints.get("rShoulder") or joints.get("head"):
                        detected_frames += 1
                    # wrist swap correction for pose (fast crossing)
                    cur_lw = joints.get("lWrist")
                    cur_rw = joints.get("rWrist")
                    if cur_lw is not None and cur_rw is not None and prev_lWrist is not None and prev_rWrist is not None:
                        new_l, new_r, swapped = maybe_swap_wrists(cur_lw, cur_rw, prev_lWrist, prev_rWrist)
                        if swapped:
                            print(f"[tracker] pose wrist swap corrected at frame {idx}")
                            joints["lWrist"], joints["rWrist"] = new_l, new_r

            # hands — tracker-based assignment to prevent swap when close/overlapping (C)
            if hand_landmarker is not None:
                try:
                    hand_res = hand_landmarker.detect(mp_image)
                except Exception as e:
                    print(f"[mediapipe] hand detect err: {e}")
                    hand_res = None
                if hand_res and hand_res.hand_landmarks and hand_res.handedness:
                    # build detected list with centroids in normalized image space for tracking
                    detected = []
                    for lm_list, handed in zip(hand_res.hand_landmarks, hand_res.handedness):
                        cat = handed[0].category_name if handed and handed[0].category_name else "Unknown"
                        conf = float(handed[0].score) if handed and hasattr(handed[0], 'score') else 0.5
                        # centroid as wrist normalized
                        p0 = lm_list[0]
                        centroid = (float(p0.x), float(p0.y), 0.0, conf)
                        # also keep normalized centroid for tracker (0-1)
                        centroid_norm = (float(p0.x), float(p0.y))
                        detected.append({"lm_list": lm_list, "handedness": cat, "conf": conf, "centroid": centroid, "centroid_norm": centroid_norm, "handedness_raw": handed})
                    # use tracker with prev normalized centroids
                    prev_l_cent = (prev_lHand[0], prev_lHand[1]) if prev_lHand and space == "image" else None
                    # for world, prev is meters, need to convert to normalized via w/h approx: use image centroid history
                    # keep separate prev norm history
                    if not hasattr(hand_landmarker, "_prev_l_norm"):
                        hand_landmarker._prev_l_norm = None  # type: ignore
                        hand_landmarker._prev_r_norm = None  # type: ignore
                    prev_l_norm = getattr(hand_landmarker, "_prev_l_norm")
                    prev_r_norm = getattr(hand_landmarker, "_prev_r_norm")
                    # build prev JointVal for tracker in normalized space
                    prev_l_j = (prev_l_norm[0], prev_l_norm[1], 0, 1.0) if prev_l_norm else None
                    prev_r_j = (prev_r_norm[0], prev_r_norm[1], 0, 1.0) if prev_r_norm else None
                    # also consider wrist positions for better assignment
                    prev_lw_j = None
                    prev_rw_j = None
                    if prev_lWrist is not None:
                        # convert wrist to normalized if image, else keep meters but tracker uses normalized, so skip
                        if space == "image":
                            prev_lw_j = (prev_lWrist[0]/w, prev_lWrist[1]/h, 0, 1.0) if w and h else None
                        else:
                            # for world, use normalized centroid history instead
                            prev_lw_j = None
                    if prev_rWrist is not None and space == "image":
                        prev_rw_j = (prev_rWrist[0]/w, prev_rWrist[1]/h, 0, 1.0) if w and h else None
                    # prepare detected for tracker in normalized space
                    det_for_tracker = []
                    for d in detected:
                        det_for_tracker.append({"lm_list": d["lm_list"], "handedness": d["handedness"], "conf": d["conf"], "centroid": (d["centroid_norm"][0], d["centroid_norm"][1], 0, d["conf"]), "centroid_norm": d["centroid_norm"]})
                    assigned = assign_hands(det_for_tracker, prev_l_j, prev_r_j, prev_lw_j, prev_rw_j)
                    # update prev norm
                    if assigned["l"] is not None:
                        hand_landmarker._prev_l_norm = assigned["l"]["centroid_norm"]  # type: ignore
                    # keep previous if no detection for that side (avoid flicker, but don't update)
                    if assigned["r"] is not None:
                        hand_landmarker._prev_r_norm = assigned["r"]["centroid_norm"]  # type: ignore
                    # now write joints for assigned hands
                    for side, det in [("l", assigned["l"]), ("r", assigned["r"])]:
                        if det is None:
                            continue
                        lm_list = det["lm_list"]
                        prefix = side
                        anchor = joints.get(f"{prefix}Wrist")
                        # find original index for hand_world
                        use_world = space == "world" and hasattr(hand_res, "hand_world_landmarks") and hand_res.hand_world_landmarks
                        idx_hand = None
                        if use_world:
                            try:
                                idx_hand = hand_res.hand_landmarks.index(lm_list)
                            except ValueError:
                                idx_hand = None
                        if use_world and anchor is not None and idx_hand is not None:
                            try:
                                wlm = hand_res.hand_world_landmarks[idx_hand] if idx_hand < len(hand_res.hand_world_landmarks) else None
                                if wlm:
                                    ax, ay, az = anchor[0], anchor[1], anchor[2]
                                    def hp_world(i):
                                        p = wlm[i]
                                        return (ax + float(p.x), ay + float(p.y), az + float(p.z), 1.0)
                                    def hp(i): return hp_world(i)
                                else:
                                    raise IndexError
                            except Exception:
                                def hp(i):
                                    p = lm_list[i]
                                    if space == "image":
                                        return (float(p.x) * w, float(p.y) * h, float(p.z) * w, 1.0)
                                    if anchor is not None:
                                        return (anchor[0] + (float(p.x)-0.5)*0.18, anchor[1] + (0.5-float(p.y))*0.18, anchor[2] + float(p.z)*0.05, 1.0)
                                    return (float(p.x), float(p.y), float(p.z), 1.0)
                        else:
                            def hp(i):
                                p = lm_list[i]
                                if space == "image":
                                    return (float(p.x) * w, float(p.y) * h, float(p.z) * w, 1.0)
                                if anchor is not None:
                                    return (anchor[0] + (float(p.x)-0.5)*0.18, anchor[1] + (0.5-float(p.y))*0.18, anchor[2] + float(p.z)*0.05, 1.0)
                                return (float(p.x), float(p.y), float(p.z), 1.0)
                        try:
                            joints[f"{prefix}Hand"] = hp(0)
                            joints[f"{prefix}Thumb1"] = hp(2)
                            joints[f"{prefix}Thumb2"] = hp(4)
                            joints[f"{prefix}Index1"] = hp(5)
                            joints[f"{prefix}Index2"] = hp(8)
                            joints[f"{prefix}Middle1"] = hp(9)
                            joints[f"{prefix}Middle2"] = hp(12)
                            joints[f"{prefix}Ring1"] = hp(13)
                            joints[f"{prefix}Ring2"] = hp(16)
                            joints[f"{prefix}Pinky1"] = hp(17)
                            joints[f"{prefix}Pinky2"] = hp(20)
                        except Exception:
                            pass
                    # log swap correction
                    if len(detected) == 2:
                        # check if assignment differs from naive handedness
                        naive_l = next((d for d in detected if d["handedness"].lower()=="left"), None)
                        naive_r = next((d for d in detected if d["handedness"].lower()=="right"), None)
                        if assigned["l"] is not None and naive_l is not None and assigned["l"]["lm_list"] is not naive_l["lm_list"]:
                            print(f"[tracker] hand swap corrected at frame {idx}: handedness {naive_l['handedness']}/{naive_r['handedness'] if naive_r else 'none'} -> tracked l/r swapped due to proximity")
                # update prev wrist for next frame (for tracking)
                if joints.get("lWrist") is not None:
                    prev_lWrist = joints["lWrist"]
                if joints.get("rWrist") is not None:
                    prev_rWrist = joints["rWrist"]
                if joints.get("lHand") is not None:
                    prev_lHand = joints["lHand"]
                if joints.get("rHand") is not None:
                    prev_rHand = joints["rHand"]
        except Exception as e:
            print(f"[mediapipe] frame {idx} error: {e}")

        frames.append(SkeletonFrame(index=idx, timestamp=idx / fps, joints=joints))
        idx += 1

    cap.release()
    try:
        pose_landmarker.close()
        if hand_landmarker:
            hand_landmarker.close()
    except Exception:
        pass

    if not frames:
        print("[mediapipe] no frames processed")
        return None

    print(f"[mediapipe tasks] processed {len(frames)} frames, detected pose in {detected_frames}")
    if detected_frames == 0:
        print("[mediapipe] WARNING: 0 frames had pose detection — video may have no visible person or is backlit/cropped")

    space_label = "image (Y down, pixels)" if space == "image" else "world (Y down, meters, cheap-3D)"
    meta = SkeletonMeta(
        schema="source_skeleton.v1",
        space=space_label,
        fps=fps,
        frameCount=len(frames),
        duration=len(frames) / fps if fps else 0,
        joints=CANONICAL_JOINTS,
        source_video=str(video_path.name),
        estimator="mediapipe tasks pose+hand (lite)",
        coordinate_space=space_label,
    )
    return SkeletonStreamDict(meta=meta, frames=frames)


def _try_mediapipe_legacy_extract(video_path: Path, space: Space, fps: float) -> SkeletonStreamDict | None:
    try:
        import mediapipe as mp  # type: ignore

        mp_pose = mp.solutions.pose  # type: ignore
        mp_hands = mp.solutions.hands  # type: ignore
    except Exception:
        return None

    if cv2 is None:
        return None

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None

    frames: List[SkeletonFrame] = []
    idx = 0
    # Use combined Holistic if available (pose+hand+face in one pass) for efficiency
    use_holistic = hasattr(mp.solutions, "holistic")
    try:
        if use_holistic:
            holistic = mp.solutions.holistic.Holistic(  # type: ignore
                static_image_mode=False, model_complexity=1, enable_segmentation=False, refine_face_landmarks=False
            )
            pose = None
            hands = None
        else:
            holistic = None
            pose = mp_pose.Pose(static_image_mode=False, model_complexity=1, enable_segmentation=False)  # type: ignore
            hands = mp_hands.Hands(static_image_mode=False, max_num_hands=2)  # type: ignore
    except Exception:
        return None

    mp_frames = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        joints = {j.name: None for j in CANONICAL_JOINTS}

        try:
            if holistic is not None:
                res = holistic.process(rgb)  # type: ignore
                # pose world vs image
                if space == "world" and res.pose_world_landmarks:
                    lm = res.pose_world_landmarks.landmark  # type: ignore
                    # world landmarks are meters, hip-centered roughly
                    def wpt(i):  # type: ignore
                        p = lm[i]
                        return (p.x, p.y, p.z, getattr(p, "visibility", 1.0))

                    # coarse map mediapipe pose indices → canonical
                    # mp pose: 0 nose, 11 lShoulder, 12 rShoulder, 13 lElbow, 14 rElbow, 15 lWrist, 16 rWrist, 23 lHip,24 rHip,25 lKnee,26 rKnee,27 lAnkle,28 rAnkle
                    joints["head"] = wpt(0)
                    joints["lShoulder"] = wpt(11)
                    joints["rShoulder"] = wpt(12)
                    joints["lElbow"] = wpt(13)
                    joints["rElbow"] = wpt(14)
                    joints["lWrist"] = wpt(15)
                    joints["rWrist"] = wpt(16)
                    joints["lHip"] = wpt(23)
                    joints["rHip"] = wpt(24)
                    joints["lKnee"] = wpt(25)
                    joints["rKnee"] = wpt(26)
                    joints["lAnkle"] = wpt(27)
                    joints["rAnkle"] = wpt(28)
                    joints["hips"] = ((wpt(23)[0] + wpt(24)[0]) / 2, (wpt(23)[1] + wpt(24)[1]) / 2, (wpt(23)[2] + wpt(24)[2]) / 2, 1.0)
                    joints["chest"] = ((wpt(11)[0] + wpt(12)[0]) / 2, (wpt(11)[1] + wpt(12)[1]) / 2, (wpt(11)[2] + wpt(12)[2]) / 2, 1.0)
                    joints["spine"] = ((joints["hips"][0] + joints["chest"][0]) / 2, (joints["hips"][1] + joints["chest"][1]) / 2, (joints["hips"][2] + joints["chest"][2]) / 2, 1.0)
                    joints["neck"] = ((joints["chest"][0] + joints["head"][0]) / 2, (joints["chest"][1] + joints["head"][1]) / 2, (joints["chest"][2] + joints["head"][2]) / 2, 1.0)
                    # hands: world not available in holistic world, fallback to image hand landmarks projected
                    if res.left_hand_landmarks:
                        hl = res.left_hand_landmarks.landmark  # type: ignore

                        def hpt(i):  # type: ignore
                            p = hl[i]
                            return (p.x, p.y, p.z, 1.0)

                        joints["lHand"] = hpt(0)
                        joints["lThumb1"] = hpt(2)
                        joints["lThumb2"] = hpt(4)
                        joints["lIndex1"] = hpt(5)
                        joints["lIndex2"] = hpt(8)
                        joints["lMiddle1"] = hpt(9)
                        joints["lMiddle2"] = hpt(12)
                        joints["lRing1"] = hpt(13)
                        joints["lRing2"] = hpt(16)
                        joints["lPinky1"] = hpt(17)
                        joints["lPinky2"] = hpt(20)
                    if res.right_hand_landmarks:
                        hl = res.right_hand_landmarks.landmark  # type: ignore

                        def hpt2(i):  # type: ignore
                            p = hl[i]
                            return (p.x, p.y, p.z, 1.0)

                        joints["rHand"] = hpt2(0)
                        joints["rThumb1"] = hpt2(2)
                        joints["rThumb2"] = hpt2(4)
                        joints["rIndex1"] = hpt2(5)
                        joints["rIndex2"] = hpt2(8)
                        joints["rMiddle1"] = hpt2(9)
                        joints["rMiddle2"] = hpt2(12)
                        joints["rRing1"] = hpt2(13)
                        joints["rRing2"] = hpt2(16)
                        joints["rPinky1"] = hpt2(17)
                        joints["rPinky2"] = hpt2(20)
                else:
                    # image space (pixels-ish normalized 0..1 * w/h)
                    if res.pose_landmarks:
                        lm = res.pose_landmarks.landmark  # type: ignore

                        def ipt(i):  # type: ignore
                            p = lm[i]
                            return (p.x * w, p.y * h, p.z * w, getattr(p, "visibility", 1.0))

                        joints["head"] = ipt(0)
                        joints["lShoulder"] = ipt(11)
                        joints["rShoulder"] = ipt(12)
                        joints["lElbow"] = ipt(13)
                        joints["rElbow"] = ipt(14)
                        joints["lWrist"] = ipt(15)
                        joints["rWrist"] = ipt(16)
                        joints["lHip"] = ipt(23)
                        joints["rHip"] = ipt(24)
                        joints["lKnee"] = ipt(25)
                        joints["rKnee"] = ipt(26)
                        joints["lAnkle"] = ipt(27)
                        joints["rAnkle"] = ipt(28)
                        joints["hips"] = ((ipt(23)[0] + ipt(24)[0]) / 2, (ipt(23)[1] + ipt(24)[1]) / 2, (ipt(23)[2] + ipt(24)[2]) / 2, 1.0)
                        joints["chest"] = ((ipt(11)[0] + ipt(12)[0]) / 2, (ipt(11)[1] + ipt(12)[1]) / 2, (ipt(11)[2] + ipt(12)[2]) / 2, 1.0)
                        joints["spine"] = ((joints["hips"][0] + joints["chest"][0]) / 2, (joints["hips"][1] + joints["chest"][1]) / 2, (joints["hips"][2] + joints["chest"][2]) / 2, 1.0)
                        joints["neck"] = ((joints["chest"][0] + joints["head"][0]) / 2, (joints["chest"][1] + joints["head"][1]) / 2, (joints["chest"][2] + joints["head"][2]) / 2, 1.0)
                    # hands
                    if res.left_hand_landmarks:
                        hl = res.left_hand_landmarks.landmark  # type: ignore

                        def hpt(i):  # type: ignore
                            p = hl[i]
                            return (p.x * w, p.y * h, p.z * w, 1.0)

                        joints["lHand"] = hpt(0)
                        joints["lThumb1"] = hpt(2)
                        joints["lThumb2"] = hpt(4)
                        joints["lIndex1"] = hpt(5)
                        joints["lIndex2"] = hpt(8)
                        joints["lMiddle1"] = hpt(9)
                        joints["lMiddle2"] = hpt(12)
                        joints["lRing1"] = hpt(13)
                        joints["lRing2"] = hpt(16)
                        joints["lPinky1"] = hpt(17)
                        joints["lPinky2"] = hpt(20)
                    if res.right_hand_landmarks:
                        hl = res.right_hand_landmarks.landmark  # type: ignore

                        def hpt2(i):  # type: ignore
                            p = hl[i]
                            return (p.x * w, p.y * h, p.z * w, 1.0)

                        joints["rHand"] = hpt2(0)
                        joints["rThumb1"] = hpt2(2)
                        joints["rThumb2"] = hpt2(4)
                        joints["rIndex1"] = hpt2(5)
                        joints["rIndex2"] = hpt2(8)
                        joints["rMiddle1"] = hpt2(9)
                        joints["rMiddle2"] = hpt2(12)
                        joints["rRing1"] = hpt2(13)
                        joints["rRing2"] = hpt2(16)
                        joints["rPinky1"] = hpt2(17)
                        joints["rPinky2"] = hpt2(20)
            else:
                # fallback pose+hands separate
                pass
        except Exception:
            pass

        frames.append(SkeletonFrame(index=idx, timestamp=idx / fps, joints=joints))
        idx += 1
        mp_frames += 1

    cap.release()
    try:
        if holistic is not None:
            holistic.close()  # type: ignore
        if pose is not None:
            pose.close()  # type: ignore
        if hands is not None:
            hands.close()  # type: ignore
    except Exception:
        pass

    if not frames:
        return None

    # if every frame had no detections (all None), signal failure so caller falls back
    has_any = any(any(v is not None for v in f.joints.values()) for f in frames)
    if not has_any:
        return None

    space_label = "image (Y down, pixels)" if space == "image" else "world (Y down, meters, cheap-3D)"
    meta = SkeletonMeta(
        schema="source_skeleton.v1",
        space=space_label,
        fps=fps,
        frameCount=len(frames),
        duration=len(frames) / fps if fps else 0,
        joints=CANONICAL_JOINTS,
        source_video=str(video_path.name),
        estimator="mediapipe holistic (legacy)",
        coordinate_space=space_label,
    )
    return SkeletonStreamDict(meta=meta, frames=frames)


class MediaPipeExtractor(Extractor):
    @property
    def name(self) -> str:
        return "mediapipe"

    @property
    def joint_specs(self) -> List[JointSpec]:
        return CANONICAL_JOINTS

    def extract(self, video_path: Path, space: Space = "world") -> SkeletonStreamDict:
        # probe fps/frame_count for dummy fallback
        fps = 30.0
        n = 0
        if cv2 is not None:
            try:
                cap = cv2.VideoCapture(str(video_path))
                raw_fps = cap.get(cv2.CAP_PROP_FPS)
                if raw_fps and not math.isnan(raw_fps) and raw_fps >= 1:
                    fps = float(raw_fps)
                n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                cap.release()
            except Exception:
                pass

        # try real extractors in order
        res = _try_mediapipe_tasks_extract(video_path, space, fps)
        if res is not None:
            return res
        res2 = _try_mediapipe_legacy_extract(video_path, space, fps)
        if res2 is not None:
            return res2

        # fallback: dummy motion (keeps pipeline demonstrably working without mediapipe)
        return _dummy_stream(video_path, fps, n, space)
