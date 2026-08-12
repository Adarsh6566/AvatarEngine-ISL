# Offline Pipeline — Design

## Architecture
Six sequential stages, each a pure function `stage(input, config) -> output`.
Every inter-stage result is a serialized artifact on disk, so stages are
independently runnable, testable, and resumable.

```
Video → PoseExtraction → MotionReconstruction → Normalization → Retargeting → Export
ClipMeta  PoseSequence     SkeletalMotion       NormalizedMotion  RetargetedMotion  MotionAsset(.vrma)
```

## Data flow (models in `models.py`)
| Boundary | Model | Meaning |
|---|---|---|
| input | `ClipMeta` | one video + provenance (signer, consent, license) |
| after extraction | `PoseSequence` | per-frame landmarks, estimator-tagged |
| after reconstruction | `SkeletalMotion` | canonical-skeleton joint rotations |
| after normalization | `NormalizedMotion` | canonicalized: fixed fps, scale, facing, trimmed |
| after retargeting | `RetargetedMotion` | VRM humanoid bone tracks |
| output | `MotionAsset` | `.vrma` path + `ManifestFragment` |

## Module responsibilities
- `models.py` — data contracts (fields only).
- `io.py` — read/write artifacts (decouples stages).
- `config.py` — `PipelineConfig`: fps, estimator name, skeleton map, retarget profile.
- `ingest.py` / `reconstruct.py` / `normalize.py` / `retarget.py` / `export_vrma.py` — the stages.
- `evaluation.py` — quality metrics used to validate the spike.
- `pipeline.py` — `Pipeline` orchestrator + `PipelineStage` protocol.
- `estimators/` — pluggable pose estimators (`base.PoseEstimator` + `registry`).

## Extension points
1. **New pose estimator** (MediaPipe/OpenPose/…): add an `estimators/<name>.py`
   implementing `PoseEstimator`, register it. Nothing downstream changes — every
   estimator maps its native landmarks into the canonical `landmark_set`.
2. **Pre-reconstructed sources** (SignAvatars/SMPL-X): join at the `SkeletalMotion`
   boundary, skipping extraction — because each boundary is a public artifact.
3. **New target rig**: add a `RetargetProfile` (source-skeleton → VRM bone map),
   selected via config.

```
raw video ─► [MediaPipe|OpenPose|…] ─► PoseSequence ─┐
                                                      ├─► SkeletalMotion ─► … ─► VRMA
SignAvatars (SMPL-X) ────────────────────────────────┘  (joins here)
```
