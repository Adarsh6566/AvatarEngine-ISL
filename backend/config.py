"""Load universal config.yaml with env overrides — modular config layer (P2-6).

Env vars win over yaml so deploy can override without editing files:
  FRONTEND_ORIGIN, BACKEND_PORT, VITE_API_URL (frontend only)
"""
from __future__ import annotations

import os
from pathlib import Path
from functools import lru_cache

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    yaml = None  # type: ignore[assignment]

_DEFAULTS = {
    "backend": {
        "host": "127.0.0.1",
        "port": 8000,
        "cors": {
            "frontend_origin": "http://localhost:5173,http://127.0.0.1:5173",
            "allow_methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization"],
        },
        "validation": {"text_max_length": 500, "text_min_length": 1},
        "rate_limit": {"requests_per_min": 30, "window_seconds": 60},
        "log_level": "INFO",
        "max_body_bytes": 8192,
        "dictionary": {"path": "backend/vocabulary.json", "manifest_path": "data/motion_manifest.json"},
    },
    "frontend": {"dev_port": 5173, "api_url": "http://127.0.0.1:8000", "timeout_ms": 8000, "validation": {"text_max_length": 500}},
    "animation": {
        "gesture_fade_seconds": 0.6,
        "min_hold_seconds": 1.5,
        "max_hold_seconds": 3,
        "missing_motion_seconds": 1.5,
        "word_gap_seconds": 0,
        "fingerspell": {"hold_seconds": 2, "fade_seconds": 0.25},
        "playback_speeds": [1, 2, 3, 4, 5],
        "default_speed": 1,
    },
    "avatar": {
        "model_path": "/models/AvatarSample_C.vrm",
        "concurrency": 6,
        "word_priority": ["HELLO", "THANKYOU", "PLEASE", "SORRY", "YES", "NO", "ME", "YOU", "BYE"],
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)  # type: ignore[arg-type]
        else:
            out[k] = v
    return out


def _validate_and_normalize(cfg: dict) -> dict:
    import logging

    log = logging.getLogger("avatar-engine")
    # Port range
    try:
        port = int(cfg["backend"]["port"])
        if not 1 <= port <= 65535:
            raise ValueError
        cfg["backend"]["port"] = port
    except Exception:
        log.warning("invalid backend.port %r — falling back to 8000", cfg["backend"].get("port"))
        cfg["backend"]["port"] = 8000

    # CORS origins: must be http(s)://, normalize trailing slash
    raw = cfg["backend"]["cors"].get("frontend_origin", "")
    parts = [o.strip().rstrip("/") for o in str(raw).split(",") if o.strip()]
    cleaned: list[str] = []
    for o in parts:
        if not o.startswith(("http://", "https://")):
            log.warning("invalid CORS origin %r — skipping", o)
            continue
        cleaned.append(o)
    if not cleaned:
        log.warning("no valid CORS origins — using default")
        cleaned = ["http://localhost:5173", "http://127.0.0.1:5173"]
    cfg["backend"]["cors"]["frontend_origin"] = ",".join(cleaned)
    return cfg


@lru_cache(maxsize=1)
def load_config() -> dict:
    import logging

    cfg: dict = dict(_DEFAULTS)
    # Try repo-root config.yaml or infra/config.yaml (future clean layout)
    candidates = [Path(__file__).parent.parent / "config.yaml", Path(__file__).parent.parent / "infra" / "config.yaml"]
    yaml_path = next((p for p in candidates if p.exists()), candidates[0])
    if yaml and yaml_path.exists():
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                cfg = _deep_merge(cfg, data)
            else:
                logging.getLogger("avatar-engine").warning("config.yaml not a dict — using defaults")
        except Exception as exc:
            logging.getLogger("avatar-engine").warning("config.yaml malformed (%s) — using defaults", exc)

    # Env overrides
    if os.getenv("FRONTEND_ORIGIN"):
        cfg["backend"]["cors"]["frontend_origin"] = os.getenv("FRONTEND_ORIGIN", "")
    if os.getenv("BACKEND_HOST"):
        cfg["backend"]["host"] = os.getenv("BACKEND_HOST", "127.0.0.1")
    if os.getenv("BACKEND_PORT"):
        try:
            cfg["backend"]["port"] = int(os.getenv("BACKEND_PORT", "8000"))
        except ValueError:
            logging.getLogger("avatar-engine").warning("invalid BACKEND_PORT %r", os.getenv("BACKEND_PORT"))
    if os.getenv("VITE_API_URL") is not None:
        cfg["frontend"]["api_url"] = os.getenv("VITE_API_URL", "")
    if os.getenv("LOG_LEVEL"):
        cfg["backend"]["log_level"] = os.getenv("LOG_LEVEL", "INFO")
    if os.getenv("DICTIONARY_PATH"):
        cfg["backend"]["dictionary"]["path"] = os.getenv("DICTIONARY_PATH", "backend/vocabulary.json")

    return _validate_and_normalize(cfg)


def get_cors_origins() -> list[str]:
    raw = load_config()["backend"]["cors"]["frontend_origin"]
    return [o.strip() for o in str(raw).split(",") if o.strip()]


def get_validation_limits() -> tuple[int, int]:
    v = load_config()["backend"]["validation"]
    return int(v.get("text_min_length", 1)), int(v.get("text_max_length", 500))


def get_rate_limit() -> tuple[int, float]:
    r = load_config()["backend"].get("rate_limit", {})
    return int(r.get("requests_per_min", 30)), float(r.get("window_seconds", 60))


def get_log_level() -> str:
    return str(load_config()["backend"].get("log_level", "INFO"))


def get_dictionary_path() -> str:
    return str(load_config()["backend"].get("dictionary", {}).get("path", "backend/vocabulary.json"))


def get_manifest_path() -> str:
    return str(load_config()["backend"].get("dictionary", {}).get("manifest_path", "data/motion_manifest.json"))
