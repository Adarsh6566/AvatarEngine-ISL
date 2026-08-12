"""MediaPipe Holistic pose estimator.

Turns one RGB video into a canonical PoseSequence (pose + both hands + face).
MediaPipe/OpenCV are imported lazily inside estimate(), so importing this module
(and registering the estimator) never requires the CV stack to be installed.

MediaPipe data structures never leave this module — the only output type is the
project's PoseSequence.
"""
from __future__ import annotations

from ..models import ClipMeta, Landmark, PoseFrame, PoseSequence
from .base import PoseEstimator
from . import registry

# Canonical taxonomy this estimator emits (33 pose + 21+21 hands + 468 face).
LANDMARK_SET = "mp_holistic_v1"


class MediaPipePoseEstimator(PoseEstimator):
    """PoseEstimator backed by mediapipe.solutions.holistic."""

    name = "mediapipe_holistic"

    def estimate(
        self,
        video_path: str,
        meta: ClipMeta,
        *,
        max_frames: int | None = None,
        stride: int = 1,
    ) -> PoseSequence:
        """Extract landmarks frame-by-frame into a PoseSequence.

        max_frames / stride bound the work for quick validation runs.
        """
        import cv2  # lazy
        import mediapipe as mp  # lazy

        holistic_mod = mp.solutions.holistic
        self._pose_names = mp.solutions.pose.PoseLandmark
        self._hand_names = mp.solutions.hands.HandLandmark

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"could not open video: {video_path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0

        frames: list[PoseFrame] = []
        try:
            with holistic_mod.Holistic(
                static_image_mode=False,
                model_complexity=1,
                refine_face_landmarks=False,
            ) as holistic:
                index = 0
                while True:
                    ok, bgr = cap.read()
                    if not ok:
                        break
                    if index % stride == 0:
                        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                        rgb.flags.writeable = False
                        result = holistic.process(rgb)
                        t = index / fps if fps else float(index)
                        frames.append(PoseFrame(t=t, landmarks=self._collect(result)))
                        if max_frames and len(frames) >= max_frames:
                            break
                    index += 1
        finally:
            cap.release()

        return PoseSequence(
            landmark_set=LANDMARK_SET,
            estimator=f"{self.name}@{mp.__version__}",
            fps=fps or (meta.fps or 0.0),
            space="normalized",
            frames=frames,
            meta=meta,
        )

    # --- MediaPipe -> canonical (private) ----------------------------------

    def _collect(self, result) -> dict[str, Landmark]:
        """Flatten Holistic's four landmark groups into one canonical dict."""
        out: dict[str, Landmark] = {}
        self._add(out, result.pose_landmarks, "POSE", self._pose_names, use_visibility=True)
        self._add(out, result.left_hand_landmarks, "LEFT_HAND", self._hand_names)
        self._add(out, result.right_hand_landmarks, "RIGHT_HAND", self._hand_names)
        self._add(out, result.face_landmarks, "FACE", names=None)
        return out

    @staticmethod
    def _add(out, group, prefix, names=None, *, use_visibility=False):
        if group is None:
            return
        for i, lm in enumerate(group.landmark):
            key = f"{prefix}_{names(i).name}" if names is not None else f"{prefix}_{i}"
            conf = float(lm.visibility) if use_visibility else 1.0
            out[key] = Landmark(name=key, x=lm.x, y=lm.y, z=lm.z, confidence=conf)


# Self-register on import (construction is cheap; no CV import here).
registry.register(MediaPipePoseEstimator())
