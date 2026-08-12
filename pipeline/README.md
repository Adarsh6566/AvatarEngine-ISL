# pipeline — 2.5D skeleton extraction (isolated, no git touch)

All code lives inside `pipeline/` per constraint. No edits outside this folder.

## Run

```bash
pip install -r pipeline/requirements.txt
uvicorn pipeline.app:app --reload --port 8001
# open http://127.0.0.1:8001/
```

Or from pipeline dir: `python -m uvicorn pipeline.app:app --port 8001` (from repo root).

- `GET /api/health` → `{status: ok}`
- `POST /api/extract?space=world|image&extractor=mediapipe|yolo` multipart `file`
- `POST /api/extract-batch` multipart `files[]` for folder uploads
- `GET /api/outputs/{name}` serves `pipeline/outputs/*.json|*.mp4`
- `GET /` serves `pipeline/frontend/` (vanilla html+css+js, no framework, no Vite)

## Flow

`Upload video/dir → probe fps → Extractor.extract(space) → to_view_space() normalize once → write outputs/ → display side-by-side + save skeleton video`

- **Extractors**: `extractor/mediapipe_extractor.py` (world cheap-3D + image 2D, dummy fallback if mediapipe missing), `extractor/yolo_extractor.py` (ultralytics fallback). Both honor `Extractor` ABC.
- **Normalization**: `extractor/normalize.py` mirrors `frontend/skeleton/SkeletonStream.ts:toViewSpace()` — Y-flip, root at `hips`, unit scale hip→head.
- **Frontend**: `frontend/index.html` dropzone + `<video>` left, `<canvas>` 2D skeleton right, toggle to 3D orbit (lazy `three` via importmap). Sync via `video.currentTime * fps`.

## Outputs (gitignored)

`pipeline/outputs/{stem}_{id}.json` — `source_skeleton.v1 → view` with `meta`+`frames`  
`pipeline/outputs/{stem}_{id}_skeleton.mp4` — skeleton-only  
`pipeline/outputs/{stem}_{id}_overlay.mp4` — dimmed source + skeleton (if source frames available)

JSON is rig-mappable: `hips` root, parent hierarchy in `meta.joints`, `[x,y,z,conf]` per joint, `space` tag `image|world|view`.

## 2.5D cheap-3D

Default `space=world` returns world landmarks (meters, Y-up) when mediapipe is present; else dummy emits meters with `z` sinusoid. `space=image` returns pixel Y-down (flipped in normalize). Frontend has a view toggle — data is always 3D-capable, renderer decides 2D vs 3D.
