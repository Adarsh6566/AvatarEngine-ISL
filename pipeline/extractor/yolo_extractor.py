"""
YOLO fallback extractor — uses Ultralytics if installed, else delegates to dummy.

Kept trivial so the server never crashes if ultralytics is absent.
For 3D (space=world) YOLO is 2D-only so we return z=0.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import List

from .base import Extractor, Space
from .mediapipe_extractor import _dummy_stream
from .schemas import CANONICAL_JOINTS, JointSpec, SkeletonFrame, SkeletonMeta, SkeletonStreamDict


class YoloExtractor(Extractor):
    @property
    def name(self) -> str:
        return "yolo"

    @property
    def joint_specs(self) -> List[JointSpec]:
        return CANONICAL_JOINTS

    def extract(self, video_path: Path, space: Space = "world") -> SkeletonStreamDict:
        # try ultralytics if present
        try:
            from ultralytics import YOLO  # type: ignore

            import cv2
        except Exception:
            # no yolo — dummy keeps pipeline working
            fps = 30.0
            n = 0
            try:
                import cv2 as _cv2

                cap = _cv2.VideoCapture(str(video_path))
                raw = cap.get(_cv2.CAP_PROP_FPS)
                if raw and not math.isnan(raw) and raw >= 1:
                    fps = float(raw)
                n = int(cap.get(_cv2.CAP_PROP_FRAME_COUNT) or 0)
                cap.release()
            except Exception:
                pass
            s = _dummy_stream(video_path, fps, n, space)
            # relabel estimator
            s.meta.estimator = "dummy (yolo not installed)"
            s.meta.space = "image (Y down, pixels)" if space == "image" else "world (Y down, pixels)"
            return s

        # If we actually have YOLO, run a lightweight pose model.
        # Model download is lazy; failure falls back to dummy.
        try:
            import cv2

            # use absolute path inside pipeline/ so CWD doesn't matter (repo root vs pipeline/)
            from pathlib import Path as _P

            _yolo_pt = _P(__file__).parent.parent / "yolo11n-pose.pt"
            model_path = str(_yolo_pt) if _yolo_pt.exists() else "yolo11n-pose.pt"
            model = YOLO(model_path)  # will auto-download to pipeline/ if missing
            cap = cv2.VideoCapture(str(video_path))
            fps = cap.get(cv2.CAP_PROP_FPS)
            if not fps or math.isnan(fps) or fps < 1:
                fps = 30.0
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
                    # take largest person (first)
                    kpts = res.keypoints.xy[0].cpu().numpy()  # (17,2)
                    confs = res.keypoints.conf[0].cpu().numpy() if hasattr(res.keypoints, "conf") else [1.0] * 17
                    # COCO 17 map: 0 nose, 5 lShoulder,6 rShoulder,7 lElbow,8 rElbow,9 lWrist,10 rWrist,11 lHip,12 rHip,13 lKnee,14 rKnee,15 lAnkle,16 rAnkle
                    CONF_THRESH = 0.4
                    def kp(i):
                        conf = float(confs[i] if i < len(confs) else 1.0)
                        if conf < CONF_THRESH:
                            return None
                        return (float(kpts[i][0]), float(kpts[i][1]), 0.0, conf)

                    # only set if visible — prevents hallucinated legs when cropped/occluded
                    for k, idx in [("head",0),("lShoulder",5),("rShoulder",6),("lElbow",7),("rElbow",8),("lWrist",9),("rWrist",10),("lHip",11),("rHip",12),("lKnee",13),("rKnee",14),("lAnkle",15),("rAnkle",16)]:
                        v = kp(idx)
                        if v is not None:
                            joints[k] = v
                    # derive torso only if both sides visible
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
                    # YOLO pose has no finger detail — leave hand fingers as None
                    # (frontend will show wrists; mediapipe task is required for fingers)
                    # keep lHand/rHand as wrist copies with lower conf for stub line, but not fingers
                    if joints.get("lWrist") and joints["lHand"] is None:
                        lw = joints["lWrist"]  # type: ignore
                        joints["lHand"] = (lw[0], lw[1] + 4, 0, 0.5)
                    if joints.get("rWrist") and joints["rHand"] is None:
                        rw = joints["rWrist"]  # type: ignore
                        joints["rHand"] = (rw[0], rw[1] + 4, 0, 0.5)

                frames.append(SkeletonFrame(index=idx, timestamp=idx / fps, joints=joints))
                idx += 1
            cap.release()
            if not frames:
                raise RuntimeError("no frames")
            space_label = "image (Y down, pixels)" if space == "image" else "world (Y down, pixels)"
            meta = SkeletonMeta(
                schema="source_skeleton.v1",
                space=space_label,
                fps=fps,
                frameCount=len(frames),
                duration=len(frames) / fps,
                joints=CANONICAL_JOINTS,
                source_video=str(video_path.name),
                estimator="ultralytics yolo11n-pose (body only, no fingers — use mediapipe for hands)",
                coordinate_space=space_label,
            )
            return SkeletonStreamDict(meta=meta, frames=frames)
        except Exception as e:
            # any failure → dummy
            fps = 30.0
            n = 0
            try:
                import cv2 as _cv2

                cap = _cv2.VideoCapture(str(video_path))
                raw = cap.get(_cv2.CAP_PROP_FPS)
                if raw and not math.isnan(raw) and raw >= 1:
                    fps = float(raw)
                n = int(cap.get(_cv2.CAP_PROP_FRAME_COUNT) or 0)
                cap.release()
            except Exception:
                pass
            s = _dummy_stream(video_path, fps, n, space)
            s.meta.estimator = f"dummy (yolo failed: {e})"
            return s
