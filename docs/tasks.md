# Tasks — making avatar-engine a reliable, production-ready app

> No aesthetics. Only correctness, deployability, and failure handling.

## P0 — blocks any real deployment (do first)

- [x] **P0-1 Hard-coded backend URL** `src/api/translate.ts:3` — done 2026-08-11
  - Replace `http://127.0.0.1:8000/translate` with `import.meta.env.VITE_API_URL` (fallback `/api/translate`).
  - Add `vite.config.ts:server.proxy` for dev (`/api` → `127.0.0.1:8000`), update `src/api/translate.ts:17` to use relative URL in prod.
  - Add `.env.example` with `VITE_API_URL=`.

- [x] **P0-2 Fetch has no timeout / abort** `src/api/translate.ts:17`, `src/main.ts:59` — done 2026-08-11
  - Add `AbortController` + 8s timeout, surface timeout as distinct error. Abort previous request on re-submit.
  - Verify: slow backend returns clean error, UI re-enables.

- [x] **P0-3 CORS is `*`** `backend/app.py:11` — done 2026-08-11
  - Restrict `allow_origins` to env var (`FRONTEND_ORIGIN=http://localhost:5173`), limit `allow_methods` to `POST,GET,OPTIONS`.
  - Verify: cross-origin from non-allowed origin is rejected.

- [x] **P0-4 No health check** `backend/app.py` — done 2026-08-11
  - Add `GET /health` (200 ok) and `GET /ready` (checks vocab/alphabet loads). Used by `run.sh`, `scripts/dev.mjs:42`, and any orchestrator.
  - Verify: `curl /health` before opening browser in `run.sh`.

- [x] **P0-5 No input validation** `backend/schemas.py:4`, `src/ui/SignControls.ts:25` — done 2026-08-11
  - Backend: `text: str = Field(min_length=1, max_length=500, strip_whitespace=True)` + `422` on empty/oversize. Add `max_length` to `TranslateRequest`.
  - Frontend: `maxlength=500`, block empty submit, show `422` message.
  - Verify: `""`, `"   "`, and 10k-char input return 422, not 500.

- [x] **P0-6 Broken Python package layout** `backend/language/` (no `__init__.py`), `backend/app.py:3` — done 2026-08-11
  - Add `backend/language/__init__.py`, make imports relative or set `PYTHONPATH`. Ensure `python -m backend.app` and `uvicorn app:app` both work from repo root.
  - Add `backend/__init__.py` if packaging; fix `PIPELINE.md:339` namespace-package note.

## P1 — silent data loss / broken features

- [x] **P1-1 Digits fingerspell to nothing** `backend/language/alphabet.json:28-37` vs `src/data/motion_manifest.json` — done 2026-08-11 (leave-as-is)
  - Alphabet maps `"0"→"0"` but manifest has no `"0"` key. `segment("12")` → `["1","2"]` → `MotionCatalog.getMotion` returns `null` → `Sequencer.ts:162` caption-only hold.
  - Policy: if no animation, leave as is (no crash, no bogus token). `Sequencer:162` already holds `MISSING_MOTION_SECONDS`/`FINGERSPELL.holdSeconds` and warns; `translator.py:23` now uses `[a-z0-9]` (was `\w` which included `_`) and documents digit caption-only intent. No digit `.vrma` required.

- [x] **P1-2 Vocab casing bug** `backend/vocabulary.json:8` `"I": "ME"` — done 2026-08-11
  - `normalizer.py:7` lowercases all input, so `"I"` → `"i"` never matched `"I"`. Changed to `"i": "ME"` (verified `segment("I")→["ME"]`, all keys now lowercase).

- [x] **P1-3 Unbounded parallel gesture load** `src/avatar/controller/AvatarController.ts:111` `Promise.all` — done 2026-08-11
  - 37 `.vrma` were fetched at once. Now batched with concurrency `6` via `Promise.allSettled` per batch, word signs (`HELLO`…`BYE`) prioritized first, failures logged as `N/M registered` + `caption-only fallback` warn; does not block avatar ready (leave-as-is if missing).

- [x] **P1-4 Dead-tail clip duration** `src/sign/Sequencer.ts:36` `MAX_HOLD_SECONDS=3`, `src/data/motion_manifest.json:duration` — done 2026-08-11 (leave-as-is)
  - Clips padded to ~10s, clamp hides bad export. Manifest `duration` drifts from `AnimationController.getDuration():113` real clip length.
  - Policy: if no re-export, leave clamp as is (MAX=3, MIN=1.5) — sequencer times on `player.getDuration() ?? manifest.duration` minus fade, clamped. Trimming `.vrma` to remove dead tail is future work, no crash now.

- [x] **P1-5 `alphabet.json` digit scheme drift** `backend/language/alphabet.json` vs `PIPELINE.md:5` — done 2026-08-11
  - Docs still mentioned `LETTER_*`/`DIGIT_*` but code uses bare `A`/`0`. Fixed `PIPELINE.md:193,214,273` to bare ids and `translator.py:23` regex to `[a-z0-9]` (was `\w` which included `_`).

## P2 — hardening / modern reliability

- [x] **P2-1 Frontend error boundaries** `src/core/RenderEngine.ts`, `src/main.ts:25`, `src/avatar/loading/VrmLoader.ts:43` — done 2026-08-11
  - `RenderEngine.ts:31` checks `isWebGLAvailable()`, shows `render-fallback` alert, guards `ResizeObserver` + `renderer.dispose()` with try/catch, handles `webglcontextlost`/`restored` (pause/resume clock). `VrmLoader.readGltf` already preserves `cause`.

- [x] **P2-2 Backend error handling & observability** `backend/app.py:18` — done 2026-08-11
  - Added `X-Request-ID` middleware (timing + logging), rate limit 30/min per IP on `/translate` (429), `RequestValidationError`→422 and `Exception`→500 handlers with structured `logging` (keep `uvicorn --reload` only for dev).

- [x] **P2-3 Backend import-time crash** `backend/mapper.py:10`, `backend/language/translator.py:14` — done 2026-08-11
  - Wrapped `vocabulary.json`/`alphabet.json` loads in `_load_vocabulary()`/`_load_alphabet()` with validation (lowercase keys, string values), fallback to `{}` + warning log; `/ready` already surfaces probe failure as 503.

- [ ] **P2-4 No tests / no CI** (repo root) — skipped per request
  - Add `pytest` for `recognizer`/`translator`/`normalizer` + frontend `vitest` for `MotionCatalog`/`Sequencer` timing. Add `.github/workflows/ci.yml` running `npx tsc --noEmit`, `npm run build`, `pytest`.
  - Fix `tsconfig.json:include` to include `vite.config.ts`, `scripts/`.

- [x] **P2-5 Bundle & assets** `vite.config.ts`, `public/animations/`, `public/models/` — done 2026-08-11 (modular)
  - `vite.config.ts:18` `chunkSizeWarningLimit:600` + `manualChunks(id)` splits `three` (634k) and `three-vrm` (169k) — `npm run build` now 3 chunks (`RenderEngine`, `three-vrm`, `three`). Orphan `Please.vrma` and `AvatarSample_C.vrm` dup left as is (policy: if no animation leave as is).

- [x] **P2-6 Config & repo hygiene** (root) — done 2026-08-11
  - Created universal `config.yaml` (backend/frontend/animation/avatar) and `requirements.txt` delegating via `backend/requirements.txt: -r ../requirements.txt`; added `backend/config.py` (`load_config()` merges yaml + `FRONTEND_ORIGIN`/`BACKEND_PORT` env, defaults), wired into `backend/app.py:16` and `backend/schemas.py:5`. Synced `.env.example` header to reference `config.yaml`.

- [x] **P2-7 Recognizer concurrency note** `backend/language/recognizer.py:52` `recognize()/last()` — done 2026-08-11
  - Added `DeprecationWarning` to `recognize()`/`last()`, docs say prefer `split()`; `app.py` already uses stateless path.

---

## P3 — remaining hardcodings & prod reliability (audit 2026-08-11)

> Explore audit found 7 files still hardcode values that already exist in `config.yaml` + host/rate-limit gaps.

- [x] **P3-1 Host hardcoded `127.0.0.1`** `vite.config.ts:26`, `scripts/dev.mjs:55`, `run.sh:68,111` — done 2026-08-11
  - Proxy `target`, `net.connect` host, `curl` health, `uvicorn --host` all hardcode `127.0.0.1`. Must read `backend.host` from `config.yaml` (env `BACKEND_HOST`). Breaks Docker where `0.0.0.0` needed. Severity: must-fix for prod.

- [x] **P3-2 Frontend animation timings still hardcoded** `src/sign/Sequencer.ts:15,23,36,43-48,57` (`MISSING_MOTION_SECONDS=1.5`, `MIN_HOLD=1.5`, `MAX_HOLD=3`, `WORD_GAP=0`, `FINGERSPELL 2/0.25`), `src/avatar/animation/AnimationController.ts:22` (`GESTURE_FADE_SECONDS=0.6` + `*2.5` relax) — done 2026-08-11
  - All 7 values exist in `config.yaml:animation` but frontend never reads it. Fix: inject via Vite `define` or `fetch(/config)` at boot and pass through `main.ts` → `Sequencer`/`AvatarController`. Severity: must-fix (drift).

- [x] **P3-3 Frontend validation & speeds hardcoded** `src/ui/SignControls.ts:31,33` `500`, `src/ui/PlaybackSpeedControl.ts:17` `[1,2,3,4,5]`, `src/main.ts:123` `model_path` — done 2026-08-11
  - Duplicate `frontend.validation.text_max_length`, `animation.playback_speeds`/`default_speed`, `avatar.model_path`/`concurrency`/`word_priority`. Frontend must consume injected config; `backend/config.py:_DEFAULTS` missing `frontend.validation` and `avatar.word_priority`. Severity: must-fix.

- [x] **P3-4 Timeout & rate limit not in config** `src/api/translate.ts:9` `DEFAULT_TIMEOUT_MS=8000`, `backend/app.py:51` `_RATE_LIMIT=30`/`_WINDOW=60` (in-memory deque, resets on restart, `X-Forwarded-For` not trusted) — done 2026-08-11
  - Add `frontend.timeout_ms: 8000` and `backend.rate_limit.requests_per_min/window_seconds` to `config.yaml`, wire to `config.py` + Vite define. Replace with shared store or document single-instance. Severity: must-fix (untunable).

- [x] **P3-5 Env/config validation silent fallback** `backend/config.py:63` `except Exception: pass` swallows malformed `config.yaml` — done 2026-08-11
  - Misconfig silently falls back — deployer thinks `FRONTEND_ORIGIN` applied. Fix: validate with pydantic, log warning, surface via `GET /ready` 503 and fail-fast on bad port/CORS URL. Add `BACKEND_HOST`, `LOG_LEVEL` envs. Severity: must-fix.

- [x] **P3-6 Prod deploy gaps** `Dockerfile`/`compose` missing, `healthcheck` not wired to `/ready`, `graceful shutdown` missing, `HTTPS/TLS` via reverse proxy not documented, `auth` open `POST /translate`, `structured logging` level not from `config.yaml` (`LOG_LEVEL`), `request body size` not limited, `CORS split` naive — done 2026-08-11
  - Add `Dockerfile` + `HEALTHCHECK curl -f http://localhost:8000/ready`, `TRUSTED_PROXY` handling, `max_request_body_size`, normalize CORS origins. Severity: must-fix for public prod.

### Execution order

P0 in numeric order (P0-1 → P0-6), then P1, then P2. Each task must run `npx tsc --noEmit` and `npm run build` before marking done, and update `CHANGELOG.md` per `AGENTS.md:5`.