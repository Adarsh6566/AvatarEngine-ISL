import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

try:
    from language.translator import segment
    from schemas import Segment, TranslateRequest, TranslateResponse
    from config import get_cors_origins, get_rate_limit, get_log_level, load_config
except ImportError:  # when run as `backend.app` from repo root
    from backend.language.translator import segment  # type: ignore[no-redef]
    from backend.schemas import Segment, TranslateRequest, TranslateResponse  # type: ignore[no-redef]
    from backend.config import get_cors_origins, get_rate_limit, get_log_level, load_config  # type: ignore[no-redef]

logger = logging.getLogger("avatar-engine")
_log_level = get_log_level().upper()
logging.basicConfig(level=getattr(logging, _log_level, logging.INFO), format="%(asctime)s %(levelname)s [%(name)s] %(message)s")

app = FastAPI(title="ISL Translator")

_cfg = load_config()
_allow_origins = get_cors_origins()
_allow_methods = _cfg["backend"]["cors"].get("allow_methods", ["GET", "POST", "OPTIONS"])
_allow_headers = _cfg["backend"]["cors"].get("allow_headers", ["Content-Type", "Authorization"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_methods=_allow_methods,
    allow_headers=_allow_headers,
)


# --- observability: request ID + timing ---
@app.middleware("http")
async def add_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
    req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:8]
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("%s %s -> %s %.1fms id=%s", request.method, request.url.path, response.status_code, elapsed_ms, req_id)
    return response


# --- body size guard (backend.max_body_bytes) ---
_MAX_BODY = int(_cfg["backend"].get("max_body_bytes", 8192))


@app.middleware("http")
async def guard_body_size(request: Request, call_next):  # type: ignore[no-untyped-def]
    clen = request.headers.get("content-length")
    if clen and clen.isdigit() and int(clen) > _MAX_BODY:
        return JSONResponse(status_code=413, content={"detail": f"Payload too large (max {_MAX_BODY} bytes)"})
    return await call_next(request)


# --- rate limit: config-driven (backend.rate_limit) — in-memory, best-effort ---
_RATE_LIMIT, _WINDOW = get_rate_limit()
_hits: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def rate_limit(request: Request, call_next):  # type: ignore[no-untyped-def]
    # Only limit translate (expensive) — health/ready are cheap
    if request.url.path == "/translate":
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        q = _hits[ip]
        while q and now - q[0] > _WINDOW:
            q.popleft()
        if len(q) >= _RATE_LIMIT:
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Try again in a minute."})
        q.append(now)
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):  # type: ignore[no-untyped-def]
    logger.warning("422 %s %s id=%s", request.url.path, exc.errors(), request.headers.get("X-Request-ID", "-"))
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):  # type: ignore[no-untyped-def]
    logger.exception("500 %s id=%s", request.url.path, request.headers.get("X-Request-ID", "-"))
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", response_model=None)
def ready() -> dict[str, str] | JSONResponse:
    # Lightweight check that the translation pipeline is importable and functional.
    try:
        probe = segment("hello")
        if not probe:
            raise RuntimeError("segment returned empty for probe")
    except Exception as exc:  # pragma: no cover - startup failure
        return JSONResponse(status_code=503, content={"status": "not ready", "detail": str(exc)})
    return {"status": "ready"}


@app.post("/admin/reload-vocab", response_model=None)
def reload_vocab() -> dict[str, str] | JSONResponse:
    """Hot-reload vocabulary from disk (config path). No restart needed after offline pipeline writes new vocab."""
    try:
        try:
            from mapper import reload_vocabulary
        except ImportError:
            from backend.mapper import reload_vocabulary  # type: ignore[no-redef]

        count = reload_vocabulary()
        logger.info("vocab reloaded: %s entries", count)
        return {"status": "reloaded", "entries": str(count)}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.post("/translate", response_model=TranslateResponse)
def translate_endpoint(request: TranslateRequest) -> TranslateResponse:
    segments = segment(request.text)

    # gloss is derived from segments rather than translated separately, so the
    # two views can never disagree.
    return TranslateResponse(
        gloss=[gesture for part in segments for gesture in part.gestures],
        segments=[
            Segment(word=part.word, gestures=part.gestures, spelled=part.spelled)
            for part in segments
        ],
    )
