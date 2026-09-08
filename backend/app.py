import logging
import time
import uuid
from pathlib import Path as _Path

# .env is the pattern this repo already documents (.env.example) and already
# gitignores, but nothing was loading it — so a key placed there was silently
# ignored and only a real environment variable worked. Optional: if the package
# is missing the app still starts and reads plain environment variables.
try:
    from dotenv import load_dotenv

    load_dotenv(_Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

try:
    from language.translator import segment
    from language import gloss_llm
    from schemas import Segment, TranslateRequest, TranslateResponse
    from config import get_cors_origins, get_rate_limit, get_log_level, load_config
except ImportError:  # when run as `backend.app` from repo root
    from backend.language.translator import segment  # type: ignore[no-redef]
    from backend.language import gloss_llm  # type: ignore[no-redef]
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

# --- English -> ISL gloss, via a language model -----------------------------


class GlossVocabEntry(BaseModel):
    gloss: str = Field(max_length=64)
    words: list[str] = Field(default_factory=list, max_length=32)


class GlossRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    # The CALLER supplies its vocabulary. The signer page owns the sign library
    # (frontend/signer/SignLibrary.ts) and a second copy here would be a second
    # thing to keep correct — the lecture service avoids the same trap for the
    # same reason.
    vocabulary: list[GlossVocabEntry] = Field(min_length=1, max_length=512)


class GlossResponse(BaseModel):
    glosses: list[str]
    # "llm" when the model produced this, "unavailable" when the caller should
    # use its own matcher instead. Named so the client can report honestly
    # rather than silently presenting a fallback as a translation.
    source: str


@app.post("/gloss", response_model=GlossResponse)
def gloss_endpoint(request: GlossRequest) -> GlossResponse:
    """Translate English to a sequence of the caller's own glosses.

    Returns source="unavailable" with no glosses when translation could not be
    done — no key configured, network down, model unreachable or its reply
    unusable. That is not an error condition: the client falls back to string
    matching and keeps signing.
    """
    entries = [gloss_llm.VocabEntry(gloss=v.gloss, words=v.words) for v in request.vocabulary]
    result = gloss_llm.translate(request.text, entries)
    if result is None:
        return GlossResponse(glosses=[], source="unavailable")
    return GlossResponse(glosses=result, source="llm")


class GlossBatchRequest(BaseModel):
    # A lecture arrives as thousands of short segments. One request per segment
    # would spend the whole prompt — mostly the vocabulary listing, identical
    # every time — on each of them.
    texts: list[str] = Field(min_length=1, max_length=64)
    vocabulary: list[GlossVocabEntry] = Field(min_length=1, max_length=512)


class GlossBatchResponse(BaseModel):
    # One entry per input text, same order. Never shorter: a caller lining these
    # up against timestamped segments must not have them shift.
    results: list[list[str]]
    source: str


@app.post("/gloss/batch", response_model=GlossBatchResponse)
def gloss_batch_endpoint(request: GlossBatchRequest) -> GlossBatchResponse:
    entries = [gloss_llm.VocabEntry(gloss=v.gloss, words=v.words) for v in request.vocabulary]
    results = gloss_llm.translate_batch(request.texts, entries)
    if results is None:
        return GlossBatchResponse(results=[[] for _ in request.texts], source="unavailable")
    return GlossBatchResponse(results=results, source="llm")
