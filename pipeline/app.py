"""
pipeline/app.py — isolated FastAPI for 2.5D skeleton extraction.

Lives entirely inside pipeline/. No imports from backend/ or frontend/.
Run:  uvicorn pipeline.app:app --reload --port 8001
      or: python -m pipeline.app

Endpoints:
  GET  /health
  GET  /api/health
  POST /api/extract          multipart file + ?space=world|image&extractor=mediapipe|yolo
  POST /api/extract-batch    multipart files[]
  GET  /api/outputs/{name}   serve saved json/mp4
  GET  /                     serve pipeline/frontend/index.html
"""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import List, Literal

import cv2
from fastapi import FastAPI, File, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

try:  # works when run as `pipeline.app` from repo root
    from .extractor.mediapipe_extractor import MediaPipeExtractor
    from .extractor.normalize import to_view_space
    from .extractor.smooth import smooth_stream
    from .extractor.schemas import SkeletonStreamDict
    from .extractor.video import probe_video, write_skeleton_video
    from .extractor.yolo_extractor import YoloExtractor
    from .extractor.hybrid_yolo_mediapipe import HybridYoloMediapipeExtractor
    from .extractor.hybrid_smplx_mediapipe import HybridSmplxMediapipeExtractor
    from .extractor.smplx_full import SmplxFullExtractor
except ImportError:  # works when run as `app` from inside pipeline/ (uvicorn app:app)
    from extractor.mediapipe_extractor import MediaPipeExtractor  # type: ignore
    from extractor.normalize import to_view_space  # type: ignore
    from extractor.smooth import smooth_stream  # type: ignore
    from extractor.schemas import SkeletonStreamDict  # type: ignore
    from extractor.video import probe_video, write_skeleton_video  # type: ignore
    from extractor.yolo_extractor import YoloExtractor  # type: ignore
    from extractor.hybrid_yolo_mediapipe import HybridYoloMediapipeExtractor  # type: ignore
    from extractor.hybrid_smplx_mediapipe import HybridSmplxMediapipeExtractor  # type: ignore
    from extractor.smplx_full import SmplxFullExtractor  # type: ignore

PIPELINE_DIR = Path(__file__).parent
OUTPUT_DIR = PIPELINE_DIR / "outputs"
TMP_DIR = PIPELINE_DIR / ".tmp"
CACHE_DIR = PIPELINE_DIR / ".cache"
FRONTEND_DIR = PIPELINE_DIR / "frontend"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TMP_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="pipeline — 2.5D skeleton", version="0.1.0")

# CORS: allow Vite dev + plain file:// preview
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

EXTRACTORS = {
    "mediapipe": MediaPipeExtractor(),
    "yolo": YoloExtractor(),
    "hybrid_yolo_mediapipe": HybridYoloMediapipeExtractor(),
    "hybrid_smplx_mediapipe": HybridSmplxMediapipeExtractor(),
    "smplx_full": SmplxFullExtractor(),
}


def _extractor(name: str):
    return EXTRACTORS.get(name) or EXTRACTORS["mediapipe"]


@app.get("/health")
@app.get("/api/health")
def health():
    # cuda flag for smplx modes
    try:
        import torch  # type: ignore

        cuda = bool(torch.cuda.is_available())
        torch_v = getattr(torch, "__version__", "unknown")
    except Exception:
        cuda = False
        torch_v = None
    # smplx availability (local file check, no download)
    try:
        try:
            from .extractor._smplx_common import check_smplx_available  # type: ignore
        except ImportError:
            from extractor._smplx_common import check_smplx_available  # type: ignore

        smplx_ok, smplx_detail = check_smplx_available()
    except Exception:
        smplx_ok, smplx_detail = False, "check failed"
    return {
        "status": "ok",
        "extractors": list(EXTRACTORS.keys()),
        "output_dir": str(OUTPUT_DIR.resolve()),
        "tmp_dir": str(TMP_DIR.resolve()),
        "cuda": cuda,
        "torch": torch_v,
        "smplx_available": smplx_ok,
        "smplx_detail": smplx_detail,
    }


def _save_upload_to_temp(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "input.mp4").suffix or ".mp4"
    # all temp stays inside pipeline/.tmp per user constraint
    tmp = TMP_DIR / f"pipeline_{uuid.uuid4().hex}{suffix}"
    with open(tmp, "wb") as f:
        shutil.copyfileobj(upload.file, f)
    return tmp


def _process_one(
    tmp_path: Path,
    original_name: str,
    space: Literal["image", "world"],
    extractor_name: str,
) -> dict:
    extractor = _extractor(extractor_name)
    fps, w, h, _ = probe_video(tmp_path)

    # 1. extract (image or world)
    stream: SkeletonStreamDict = extractor.extract(tmp_path, space=space)  # type: ignore

    # normalize → view space (Y-up, root hips, unit scale) — single point
    view = to_view_space(stream)
    # per-joint smoothing: spine/hips heavy deadzone, hands accurate (spec: spine allowance, hands accurate)
    try:
        view = smooth_stream(view)
    except Exception as e:
        print(f"[smooth] failed: {e}")
    run_id = f"{Path(original_name).stem}_{uuid.uuid4().hex[:6]}"
    json_path = OUTPUT_DIR / f"{run_id}.json"
    skel_mp4 = OUTPUT_DIR / f"{run_id}_skeleton.mp4"
    skel_overlay_mp4 = OUTPUT_DIR / f"{run_id}_overlay.mp4"

    # write canonical source_skeleton.v1 (pre-view) + view variant
    out_dict = {
        "meta": view.meta.model_dump(by_alias=True),
        "frames": [f.model_dump() for f in view.frames],
        "source_meta": stream.meta.model_dump(by_alias=True),
        "space_requested": space,
        "extractor": extractor_name,
        "original": original_name,
        "run_id": run_id,
    }
    # keep raw frames also accessible as meta/frames for NeonLineRenderer compat
    # add top-level 'meta'/'frames' already, also keep 'stream' alias
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(out_dict, jf, indent=2)

    # 3. render skeleton video (view-space joints)
    joints_list = [f.joints for f in view.frames]  # type: ignore
    is_3d = "world" in (stream.meta.space or "") or space == "world"
    # skeleton-only
    write_skeleton_video(joints_list, skel_mp4, fps=fps or view.meta.fps or 30.0, is_3d=is_3d, draw_original=False)
    # overlay on original frames (dimmed)
    # collect original frames for overlay (limit to len of joints_list to avoid a/v drift)
    orig_frames: List = []
    try:
        cap = cv2.VideoCapture(str(tmp_path))
        for _ in range(len(joints_list)):
            ok, fr = cap.read()
            if not ok:
                break
            orig_frames.append(fr)
        cap.release()
    except Exception:
        orig_frames = []
    if orig_frames:
        write_skeleton_video(joints_list, skel_overlay_mp4, fps=fps or 30.0, is_3d=is_3d, draw_original=True, original_frames=orig_frames)
    else:
        skel_overlay_mp4 = skel_mp4  # fallback

    return {
        "run_id": run_id,
        "original": original_name,
        "extractor": extractor_name,
        "space_requested": space,
        "space_actual": view.meta.space,
        "estimator": view.meta.estimator or stream.meta.estimator,
        "fps": view.meta.fps,
        "frameCount": view.meta.frameCount,
        "duration": view.meta.duration,
        "jointCount": len(view.meta.joints),
        "outputs": {
            "json": f"/api/outputs/{json_path.name}",
            "skeletonVideo": f"/api/outputs/{skel_mp4.name}",
            "overlayVideo": f"/api/outputs/{skel_overlay_mp4.name}",
        },
        "stream": {
            "meta": view.meta.model_dump(by_alias=True),
            "frames": [f.model_dump() for f in view.frames],
        },
    }


@app.post("/api/extract")
async def extract(
    file: UploadFile = File(...),
    space: Literal["image", "world"] = Query(default="world", description="image=2D Y-down, world=cheap-3D"),
    extractor: str = Query(default="mediapipe", description="mediapipe | yolo | hybrid_yolo_mediapipe | hybrid_smplx_mediapipe | smplx_full"),
):
    if not file.filename:
        return JSONResponse(status_code=422, content={"detail": "No file provided"})
    tmp = _save_upload_to_temp(file)
    try:
        result = _process_one(tmp, file.filename, space, extractor)  # type: ignore
        return JSONResponse(content=result)
    except FileNotFoundError as e:
        return JSONResponse(status_code=501, content={"detail": str(e), "hint": "Place SMPLX assets in pipeline/.models/smplx/ — no auto-download per config"})
    except Exception as e:
        msg = str(e)
        # SMPLX modes must be 501, not 500, per user request
        if "SMPL" in msg or "smplx" in msg.lower() or "torch" in msg.lower():
            return JSONResponse(status_code=501, content={"detail": msg, "hint": "SMPL-X not configured — see pipeline/.models/smplx/README"})
        return JSONResponse(status_code=500, content={"detail": msg})
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


@app.post("/api/extract-batch")
async def extract_batch(
    files: List[UploadFile] = File(...),
    space: Literal["image", "world"] = Query(default="world"),
    extractor: str = Query(default="mediapipe"),
):
    if not files:
        return JSONResponse(status_code=422, content={"detail": "No files"})
    out = []
    for f in files:
        tmp = _save_upload_to_temp(f)
        try:
            out.append(_process_one(tmp, f.filename or "input.mp4", space, extractor))  # type: ignore
        except FileNotFoundError as e:
            out.append({"original": f.filename, "error": str(e), "status": 501})
        except Exception as e:
            msg = str(e)
            if "SMPL" in msg or "smplx" in msg.lower():
                out.append({"original": f.filename, "error": msg, "status": 501})
            else:
                out.append({"original": f.filename, "error": msg})
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
    return JSONResponse(content={"results": out, "count": len(out)})


@app.get("/api/outputs/{name}")
def get_output(name: str):
    # prevent path traversal
    safe = Path(name).name
    path = OUTPUT_DIR / safe
    if not path.exists():
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    # guess media type
    if path.suffix == ".json":
        return FileResponse(path, media_type="application/json")
    if path.suffix == ".mp4":
        return FileResponse(path, media_type="video/mp4")
    return FileResponse(path)


# Serve frontend at /  (must be mounted after /api routes)
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


# Allow `python -m pipeline.app`
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("pipeline.app:app", host="127.0.0.1", port=8001, reload=True)
