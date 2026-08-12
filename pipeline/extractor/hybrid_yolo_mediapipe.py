"""
hybrid_yolo_mediapipe — Mode 1: YOLO body (COCO 17) + MediaPipe hands (21×2)

CPU-only, fixes V-shaped shoulders partially without SMPLX. All artifacts stay in pipeline/.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import List

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore

from .base import Extractor, Space
from .schemas import CANONICAL_JOINTS, JointSpec, SkeletonFrame, SkeletonMeta, SkeletonStreamDict

try:
    from .tracker import assign_hands, maybe_swap_wrists
except ImportError:
    from tracker import assign_hands, maybe_swap_wrists  # type: ignore

CONF_THRESH = 0.25  # lower for blurry frames
VIS_THRESH = 0.4
_HYBRID_YOLO_CACHE = None
_HYBRID_YOLO_CACHE_PATH = None


def _load_hand_landmarker():
    """Lazy create HandLandmarker from pipeline/.models/hand_landmarker.task, or None."""
    try:
        import mediapipe as mp  # type: ignore
        from mediapipe.tasks.python import vision  # type: ignore
        from mediapipe.tasks.python.core.base_options import BaseOptions  # type: ignore
        from mediapipe.tasks.python.vision.hand_landmarker import HandLandmarker  # type: ignore
    except Exception:
        return None, None
    models_dir = Path(__file__).parent.parent / ".models"
    hand_path = models_dir / "hand_landmarker.task"
    if not hand_path.exists() or hand_path.stat().st_size < 100_000:
        return None, None
    try:
        opts = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(hand_path)),
            running_mode=vision.RunningMode.IMAGE,
            num_hands=2,
            min_hand_detection_confidence=0.3,
            min_hand_presence_confidence=0.3,
            min_tracking_confidence=0.3,
        )
        return HandLandmarker.create_from_options(opts), mp  # type: ignore
    except Exception:
        return None, None


class HybridYoloMediapipeExtractor(Extractor):
    @property
    def name(self) -> str:
        return "hybrid_yolo_mediapipe"

    @property
    def joint_specs(self) -> List[JointSpec]:
        return CANONICAL_JOINTS

    def extract(self, video_path: Path, space: Space = "world") -> SkeletonStreamDict:
        # probe fps
        fps = 30.0
        n = 0
        if cv2 is not None:
            try:
                cap = cv2.VideoCapture(str(video_path))
                raw = cap.get(cv2.CAP_PROP_FPS)
                if raw and not math.isnan(raw) and raw >= 1:
                    fps = float(raw)
                n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                cap.release()
            except Exception:
                pass

        # try yolo body
        try:
            from ultralytics import YOLO  # type: ignore

            import cv2 as _cv2  # noqa: F811
        except Exception as e:
            raise RuntimeError(f"YOLO not available: {e}") from e

        # hand landmarker (optional — body still works without hands)
        hand_landmarker, mp = _load_hand_landmarker()

        try:
            # force model path inside pipeline/ (not ~/.ultralytics)
            yolo_pt = Path(__file__).parent.parent / "yolo11n-pose.pt"
            if not yolo_pt.exists():
                import os

                os.environ.setdefault("YOLO_CONFIG_DIR", str(Path(__file__).parent.parent / ".cache"))
                yolo_pt = "yolo11n-pose.pt"  # type: ignore
            global _HYBRID_YOLO_CACHE, _HYBRID_YOLO_CACHE_PATH
            model_path_str = str(yolo_pt)
            if _HYBRID_YOLO_CACHE is not None and _HYBRID_YOLO_CACHE_PATH == model_path_str:
                model = _HYBRID_YOLO_CACHE
            else:
                model = YOLO(model_path_str)  # type: ignore
                _HYBRID_YOLO_CACHE = model
                _HYBRID_YOLO_CACHE_PATH = model_path_str
            cap = _cv2.VideoCapture(str(video_path))
            fps_cap = cap.get(_cv2.CAP_PROP_FPS)
            if fps_cap and not math.isnan(fps_cap) and fps_cap >= 1:
                fps = float(fps_cap)
            frames: List[SkeletonFrame] = []
            idx = 0
            # tracker state
            prev_lWrist = None
            prev_rWrist = None
            prev_lHand = None
            prev_rHand = None
            # for hand tracker normalized history
            hand_prev_l_norm = None
            hand_prev_r_norm = None
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                h, w = frame.shape[:2]
                res = model(frame, verbose=False)[0]
                joints = {j.name: None for j in CANONICAL_JOINTS}
                if res.keypoints is not None and len(res.keypoints) > 0:
                    kpts = res.keypoints.xy[0].cpu().numpy()  # type: ignore
                    confs = res.keypoints.conf[0].cpu().numpy() if hasattr(res.keypoints, "conf") else [1.0] * 17  # type: ignore

                    def kp(i):
                        conf = float(confs[i] if i < len(confs) else 1.0)
                        if conf < CONF_THRESH:
                            return None
                        return (float(kpts[i][0]), float(kpts[i][1]), 0.0, conf)

                    for k, ci in [("head", 0), ("lShoulder", 5), ("rShoulder", 6), ("lElbow", 7), ("rElbow", 8), ("lWrist", 9), ("rWrist", 10), ("lHip", 11), ("rHip", 12), ("lKnee", 13), ("rKnee", 14), ("lAnkle", 15), ("rAnkle", 16)]:
                        v = kp(ci)
                        if v is not None:
                            joints[k] = v
                    # wrist swap correction using temporal distance
                    cur_lw = joints.get("lWrist")
                    cur_rw = joints.get("rWrist")
                    if cur_lw is not None and cur_rw is not None and prev_lWrist is not None and prev_rWrist is not None:
                        new_l, new_r, swapped = maybe_swap_wrists(cur_lw, cur_rw, prev_lWrist, prev_rWrist)
                        if swapped:
                            print(f"[tracker] YOLO wrist swap corrected at frame {idx}")
                            joints["lWrist"], joints["rWrist"] = new_l, new_r
                            cur_lw, cur_rw = new_l, new_r
                    # derive torso
                    if joints.get("lShoulder") and joints.get("rShoulder"):
                        ls, rs = joints["lShoulder"], joints["rShoulder"]
                        joints["chest"] = ((ls[0] + rs[0]) / 2, (ls[1] + rs[1]) / 2, 0, 1.0)
                    elif joints.get("lShoulder"):
                        joints["chest"] = joints["lShoulder"]
                    elif joints.get("rShoulder"):
                        joints["chest"] = joints["rShoulder"]
                    if joints.get("lHip") and joints.get("rHip"):
                        lh, rh = joints["lHip"], joints["rHip"]
                        joints["hips"] = ((lh[0] + rh[0]) / 2, (lh[1] + rh[1]) / 2, 0, 1.0)
                    elif joints.get("lHip"):
                        joints["hips"] = joints["lHip"]
                    elif joints.get("rHip"):
                        joints["hips"] = joints["rHip"]
                    if joints.get("hips") and joints.get("chest"):
                        hh, ch = joints["hips"], joints["chest"]  # type: ignore
                        joints["spine"] = ((hh[0] + ch[0]) / 2, (hh[1] + ch[1]) / 2, 0, 1.0)
                    if joints.get("chest") and joints.get("head"):
                        ch, hd = joints["chest"], joints["head"]  # type: ignore
                        joints["neck"] = ((ch[0] + hd[0]) / 2, (ch[1] + hd[1]) / 2, 0, 1.0)

                # overlay mediapipe hands — tracker prevents swap when close
                if hand_landmarker is not None and mp is not None:
                    try:
                        rgb = _cv2.cvtColor(frame, _cv2.COLOR_BGR2RGB)
                        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)  # type: ignore
                        hand_res = hand_landmarker.detect(mp_image)  # type: ignore
                        if hand_res.hand_landmarks and hand_res.handedness:
                            detected = []
                            for lm_list, handed in zip(hand_res.hand_landmarks, hand_res.handedness):
                                cat = handed[0].category_name if handed and handed[0].category_name else "Unknown"
                                conf = float(handed[0].score) if handed and hasattr(handed[0], 'score') else 0.5
                                p0 = lm_list[0]
                                centroid = (float(p0.x)*w, float(p0.y)*h, float(p0.z)*w, conf)
                                centroid_norm = (float(p0.x), float(p0.y))
                                detected.append({"lm_list": lm_list, "handedness": cat, "conf": conf, "centroid": centroid, "centroid_norm": centroid_norm})
                            # temporal assignment
                            prev_l_j = (hand_prev_l_norm[0]*w, hand_prev_l_norm[1]*h, 0, 1.0) if hand_prev_l_norm else prev_lHand
                            prev_r_j = (hand_prev_r_norm[0]*w, hand_prev_r_norm[1]*h, 0, 1.0) if hand_prev_r_norm else prev_rHand
                            det_for_tracker = []
                            for d in detected:
                                det_for_tracker.append({"lm_list": d["lm_list"], "handedness": d["handedness"], "conf": d["conf"], "centroid": (d["centroid_norm"][0], d["centroid_norm"][1], 0, d["conf"]), "centroid_norm": d["centroid_norm"]})
                            # normalize prev for tracker (0-1)
                            prev_l_norm_j = (hand_prev_l_norm[0], hand_prev_l_norm[1], 0, 1.0) if hand_prev_l_norm else None
                            prev_r_norm_j = (hand_prev_r_norm[0], hand_prev_r_norm[1], 0, 1.0) if hand_prev_r_norm else None
                            assigned = assign_hands(det_for_tracker, prev_l_norm_j, prev_r_norm_j)
                            if assigned["l"] is not None:
                                hand_prev_l_norm = assigned["l"]["centroid_norm"]
                            if assigned["r"] is not None:
                                hand_prev_r_norm = assigned["r"]["centroid_norm"]
                            for side, det in [("l", assigned["l"]), ("r", assigned["r"])]:
                                if det is None:
                                    continue
                                lm_list = det["lm_list"]
                                def hp(i):
                                    p = lm_list[i]
                                    return (float(p.x) * w, float(p.y) * h, float(p.z) * w, 1.0)
                                joints[f"{side}Hand"] = hp(0)
                                for k2, ii in [("Thumb1", 2), ("Thumb2", 4), ("Index1", 5), ("Index2", 8), ("Middle1", 9), ("Middle2", 12), ("Ring1", 13), ("Ring2", 16), ("Pinky1", 17), ("Pinky2", 20)]:
                                    joints[f"{side}{k2}"] = hp(ii)
                            if len(detected)==2:
                                # log if tracker corrected vs naive
                                naive = {d["handedness"].lower(): d for d in detected}
                                if assigned["l"] and naive.get("left") and assigned["l"]["lm_list"] is not naive["left"]["lm_list"]:
                                    print(f"[tracker] hybrid hand swap corrected at frame {idx}")
                        # update hand prev for next frame
                        if joints.get("lHand") is not None:
                            prev_lHand = joints["lHand"]
                        if joints.get("rHand") is not None:
                            prev_rHand = joints["rHand"]
                    except Exception as e:
                        print(f"[hybrid] hand detect frame {idx} err: {e}")
                # update wrist prev for next frame
                if joints.get("lWrist") is not None:
                    prev_lWrist = joints["lWrist"]
                if joints.get("rWrist") is not None:
                    prev_rWrist = joints["rWrist"]

                frames.append(SkeletonFrame(index=idx, timestamp=idx / fps, joints=joints))
                idx += 1
            cap.release()
            try:
                if hand_landmarker:
                    hand_landmarker.close()  # type: ignore
            except Exception:
                pass
            if not frames:
                raise RuntimeError("no frames decoded")
            # filter completely empty
            has_any = any(any(v is not None for v in f.joints.values()) for f in frames)
            if not has_any:
                raise RuntimeError("YOLO detected no persons")
            space_label = "image (Y down, pixels)" if space == "image" else "world (Y down, pixels)"
            meta = SkeletonMeta(
                schema="source_skeleton.v1",
                space=space_label,
                fps=fps,
                frameCount=len(frames),
                duration=len(frames) / fps if fps else 0,
                joints=CANONICAL_JOINTS,
                source_video=str(video_path.name),
                estimator="hybrid yolo(body)+mediapipe(hands)",
                coordinate_space=space_label,
            )
            return SkeletonStreamDict(meta=meta, frames=frames)
        except Exception as e:
            try:
                if 'hand_landmarker' in locals() and hand_landmarker:
                    hand_landmarker.close()  # type: ignore
            except Exception:
                pass
            raise RuntimeError(str(e)) from e
