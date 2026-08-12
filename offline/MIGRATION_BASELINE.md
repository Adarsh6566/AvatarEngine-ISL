# Migration Baseline (frozen)

Snapshot taken before the video→avatar pipeline restructuring. The **old pipeline
stays intact** as the reference baseline; the migration adds a new source-motion
path alongside it.

## Current architecture
```
Video(.MOV) → MediaPipe Holistic → PoseSequence → reconstruct.py → SkeletalMotion(13 bones)
            → normalize.py → retarget.py → RetargetedMotion → export_vrma.py → .vrma
```
Runtime (unchanged): `motion_manifest.json` → `GestureRegistry` → `AvatarController` →
`VRMAGestureLoader` → `AnimationController` plays the clip by gloss id.

## Important files (old pipeline — DO NOT MODIFY during migration)
- `offline/motionpipe/`: `reconstruct.py`, `normalize.py`, `retarget.py`, `export_vrma.py`, `models.py`, `estimators/mediapipe.py`
- `offline/templates/hello_sign.vrma` (VRMA rest template)
- Runtime: `src/data/motion_manifest.json`, `src/avatar/**` (AvatarController, GestureRegistry, AnimationController, VRMAGestureLoader), `public/animations/`

## Dataset
- Location: `offline/datasets/isl_greeting/`
- Labels: `alright, good_afternoon, good_morning, hello, how_are_you`
- Format: **`.MOV`** (QuickTime), e.g. HELLO `MVI_0029.MOV` = 25 fps, 63 frames, 1920×1080, 2.52 s.

## Runtime behavior (must remain unchanged)
- Known word → mapped VRMA (`vocabulary.json`).
- Unknown word → letter-by-letter fingerspelling (`alphabet.json`).
- Single letter works; multiple gestures play sequentially.
- Blender-authored VRMAs + one video-derived VRMA already load.

## Known problems (why we migrate)
- 543 MediaPipe landmarks reduced to 13 bones; **hands/fingers + face discarded**.
- Manual rotation/rest math → incorrect avatar poses (arms ~180°, rest-frame mismatch).
- Twist not represented.

## Checks performed (this snapshot)
- `tsc --noEmit` → exit 0.
- `python -m compileall offline/motionpipe offline/tools` → OK.
- backend `from app import app` → OK (runtime untouched).

## Must remain untouched during migration
`reconstruct.py`, `normalize.py`, `retarget.py`, `export_vrma.py`, VRM template,
`public/animations/`, `src/data/motion_manifest.json`, AvatarController,
GestureRegistry, runtime animation code, `offline/output/{motions,normalized,retargeted,animations}/`.
