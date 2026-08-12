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

CONF_THRESH = 0.4
VIS_THRESH = 0.4


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
                # fallback to ultralytics default cache, but ensure within pipeline on first download
                # ultralytics will download to cwd/pipeline
                import os

                os.environ.setdefault("YOLO_CONFIG_DIR", str(Path(__file__).parent.parent / ".cache"))
                yolo_pt = "yolo11n-pose.pt"  # type: ignore
            model = YOLO(str(yolo_pt))  # type: ignore
            cap = _cv2.VideoCapture(str(video_path))
            fps_cap = cap.get(_cv2.CAP_PROP_FPS)
            if fps_cap and not math.isnan(fps_cap) and fps_cap >= 1:
                fps = float(fps_cap)
            frames: List[SkeletonFrame] = []
            idx = 0
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

                # overlay mediapipe hands — always in image pixel space (YOLO body is pixels), then normalize flips Y
                if hand_landmarker is not None and mp is not None:
                    try:
                        rgb = _cv2.cvtColor(frame, _cv2.COLOR_BGR2RGB)
                        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)  # type: ignore
                        hand_res = hand_landmarker.detect(mp_image)  # type: ignore
                        if hand_res.hand_landmarks and hand_res.handedness:
                            for lm_list, handed in zip(hand_res.hand_landmarks, hand_res.handedness):
                                cat = handed[0].category_name if handed else "Unknown"
                                is_left = cat.lower() == "left"
                                prefix = "l" if is_left else "r"
                                # YOLO + hands both in pixel space so after to_view_space Y-flip is consistent
                                # Do not anchor to wrist with tiny delta — use absolute hand position in image
                                def hp(i):
                                    p = lm_list[i]
                                    return (float(p.x) * w, float(p.y) * h, float(p.z) * w, 1.0)

                                joints[f"{prefix}Hand"] = hp(0)
                                for k, ii in [("Thumb1", 2), ("Thumb2", 4), ("Index1", 5), ("Index2", 8), ("Middle1", 9), ("Middle2", 12), ("Ring1", 13), ("Ring2", 16), ("Pinky1", 17), ("Pinky2", 20)]:
                                    joints[f"{prefix}{k}"] = hp(ii)
                    except Exception as e:
                        print(f"[hybrid] hand detect frame {idx} err: {e}")

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
