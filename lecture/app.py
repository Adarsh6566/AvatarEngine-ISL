"""lecture — a lecture video in, timed text and the lecturer's likeness out.

    python -m uvicorn lecture.app:app --port 8002

Self-contained like pipeline/: its own FastAPI app, its own temp and output
directories, no imports from backend/ or frontend/.

What it deliberately does NOT do is decide which signs to perform. The sign
vocabulary lives in frontend/signer/SignLibrary.ts and the browser already
matches text against it; duplicating that here would mean two vocabularies
drifting apart. So this returns WHAT was said and WHEN, and the page that knows
the signs decides what to perform.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import cv2
from fastapi import FastAPI, File, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

try:
    from .fetch_url import FetchError, fetch
    from .lecturer import find_lecturer
    from .transcribe import DEFAULT_MODEL, pick_device, transcribe
except ImportError:  # running as a script rather than a package
    from fetch_url import FetchError, fetch  # type: ignore
    from lecturer import find_lecturer  # type: ignore
    from transcribe import DEFAULT_MODEL, pick_device, transcribe  # type: ignore

HERE = Path(__file__).resolve().parent
OUTPUT_DIR = HERE / "outputs"
TMP_DIR = HERE / ".tmp"
for d in (OUTPUT_DIR, TMP_DIR):
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="lecture", description="Lecture video to timed text and lecturer likeness")

# The page that consumes this is served by Vite on 5173, a different origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
@app.get("/api/health")
def health() -> dict:
    device, compute = pick_device()
    return {
        "status": "ok",
        "model": DEFAULT_MODEL,
        "device": device,
        "compute_type": compute,
        "output_dir": str(OUTPUT_DIR.resolve()),
    }


def _save_upload(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "lecture.mp4").suffix or ".mp4"
    tmp = TMP_DIR / f"lecture_{uuid.uuid4().hex}{suffix}"
    with open(tmp, "wb") as fh:
        shutil.copyfileobj(upload.file, fh)
    return tmp


@app.post("/api/transcribe")
async def api_transcribe(
    file: UploadFile = File(...),
    model: str = Query(DEFAULT_MODEL, description="whisper size: tiny|base|small|medium"),
    language: str | None = Query(None, description="ISO code, or omit to detect"),
    lecturer: bool = Query(True, description="also cut a still of the speaker"),
) -> JSONResponse:
    """Transcribe an uploaded lecture, and optionally cut out the speaker."""
    tmp = _save_upload(file)
    run_id = f"{Path(file.filename or 'lecture').stem}_{uuid.uuid4().hex[:6]}"
    try:
        result = _analyse(tmp, run_id, model, language, lecturer)
        result["original"] = file.filename
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"{type(e).__name__}: {e}"})
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _analyse(path: Path, run_id: str, model: str, language: str | None, lecturer: bool) -> dict:
    """Transcribe, and cut out the speaker. Shared by the upload and URL routes."""
    result = transcribe(path, model_size=model, language=language).to_dict()
    result["run_id"] = run_id

    if lecturer:
        try:
            shot = find_lecturer(path)
        except Exception as e:  # a missing still must not lose the transcript
            shot = None
            result["lecturer_error"] = f"{type(e).__name__}: {e}"
        if shot is not None:
            name = f"{run_id}_lecturer.jpg"
            cv2.imwrite(str(OUTPUT_DIR / name), shot.image)
            result["lecturer"] = {
                "url": f"/api/outputs/{name}",
                "timestamp": round(shot.timestamp, 2),
                "confidence": round(shot.confidence, 3),
                "box": list(shot.box),
            }
    return result


@app.post("/api/transcribe-url")
async def api_transcribe_url(
    url: str = Query(..., description="page URL of a single video"),
    model: str = Query(DEFAULT_MODEL),
    language: str | None = Query(None),
    lecturer: bool = Query(True),
) -> JSONResponse:
    """Fetch a video by URL, then analyse it exactly as an upload.

    The source's own metadata comes back with the result — who published it and
    under what licence. This pipeline exists to reuse a person's likeness, so
    that is part of the answer, not a footnote to it.
    """
    fetched = None
    try:
        fetched = fetch(url, TMP_DIR)
    except FetchError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return JSONResponse(status_code=502, content={"detail": f"{type(e).__name__}: {e}"})

    run_id = f"{fetched.path.stem}_{uuid.uuid4().hex[:6]}"
    try:
        result = _analyse(fetched.path, run_id, model, language, lecturer)
        result["original"] = fetched.title
        result["source"] = fetched.to_dict()
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": f"{type(e).__name__}: {e}"})
    finally:
        try:
            fetched.path.unlink(missing_ok=True)
        except Exception:
            pass


@app.get("/api/outputs/{name}")
def outputs(name: str):
    """Serve a produced artifact. Name is confined to OUTPUT_DIR."""
    path = (OUTPUT_DIR / name).resolve()
    if not path.is_file() or OUTPUT_DIR.resolve() not in path.parents:
        return JSONResponse(status_code=404, content={"detail": "not found"})
    return FileResponse(path)
