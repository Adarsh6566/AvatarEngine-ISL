# AGENTS.md

Operating guide for AI agents working in this repository. Read this before editing anything.

---

## 1. Project summary

**avatar-engine** is an Indian Sign Language (ISL) avatar system. A user types English text; a Python backend translates it into ISL *gloss* tokens (`HELLO`, `THANKYOU`, …); a TypeScript/Three.js frontend plays the matching `.vrma` sign animations on a 3D VRM avatar in the browser.

```
Browser (Vite + TypeScript + three.js)          Backend (FastAPI :8000)
┌────────────────────────────────┐              ┌──────────────────────────┐
│ SignControls  (text input)     │              │ POST /translate          │
│        │ translate()           │ ── HTTP ───► │  normalize → recognize   │
│        ▼                       │ ◄── gloss ── │  → dictionary.json       │
│ Sequencer                      │              │  → map_gloss             │
│   MotionCatalog → DatasetLoader│              └──────────────────────────┘
│   → MotionProcessor → Player   │
│        │ playGesture()         │
│        ▼                       │
│ AvatarController  (facade)     │
│   VrmLoader / VRMAGestureLoader│
│   AnimationController          │
│   ExpressionController         │
│   RenderEngine + Clock         │
└────────────────────────────────┘
```

Current vocabulary is **9 signs**: `HELLO`, `BYE`, `YES`, `NO`, `PLEASE`, `SORRY`, `THANKYOU`, `ME`, `YOU`.

The repo implements the **bottom two layers** of the eventual pipeline (Animation Library + VRM Avatar) plus a dictionary-lookup translator. Real NLP translation and gesture planning are deliberately not built yet.

---

## 2. Technical specification

### 2.1 Stack

| Area | Technology |
|---|---|
| Build / dev server | Vite 8 (`npm --prefix frontend run dev`, `npm --prefix frontend run build`, `npm --prefix frontend run preview`) |
| Language (frontend) | TypeScript ~6.0, ESM, `noEmit` (Vite bundles; `tsc` type-checks only) |
| 3D | three.js ^0.185, three-stdlib |
| Avatar format | `@pixiv/three-vrm` ^3.5.5 (VRM), `@pixiv/three-vrm-animation` ^3.5.5 (VRMA) |
| Backend | FastAPI 0.116.1, Uvicorn 0.35.0, Pydantic 2.11.7 |
| Python | 3.13 |

### 2.2 Repository layout

```
avatar-engine/
├── frontend/                Vite frontend (npm --prefix frontend)
│   ├── index.html           Vite entry; mounts #app, loads main.ts
│   ├── skeleton-viewer.html second Vite entry
│   ├── vite.config.ts       root: '.', publicDir: '../public', build.outDir: '../dist'
│   ├── package.json         deps + dev/build/preview (was at root)
│   ├── tsconfig.json        include: [".", "../packages", "../data"]
│   ├── main.ts              composition root — wiring only, no logic
│   ├── style.css
│   ├── api/translate.ts     fetch POST /api/translate (VITE_API_URL or Vite proxy)
│   ├── config/appConfig.ts  injected from config.yaml (Vite define __APP_CONFIG__)
│   ├── ui/SignControls.ts   + PlaybackSpeedControl + ActivityIndicator
│   ├── sign/Sequencer.ts    iterates gloss tokens, plays each in order
│   ├── motion/              MotionCatalog → DatasetLoader → Processor → Player
│   ├── skeleton/            SkeletonStream + NeonLineRenderer (VRM-free)
│   ├── viewer/skeleton-viewer.ts
│   └── avatar/              PUBLIC BARREL frontend/avatar/index.ts only
│       ├── controller/AvatarController.ts  the single public class (facade)
│       ├── loading/VrmLoader.ts / VRMAGestureLoader.ts
│       ├── animation/AnimationController.ts
│       └── expressions/ExpressionController.ts
│
├── data/                    motion_manifest.json (single source, was src/data → packages/data)
│   └── motion_manifest.json gloss → { motionId, assetPath, duration }
│
├── backend/                 FastAPI (python -m uvicorn backend.app:app)
│   ├── app.py               POST /translate, GET /health|ready, POST /admin/reload-vocab
│   ├── schemas.py           TranslateRequest 1..500 / TranslateResponse
│   ├── mapper.py            _load_vocabulary() from config dictionary.path + reload
│   ├── config.py            load_config() merges config.yaml + env
│   └── language/            normalizer / recognizer / translator / alphabet / vocabulary
│
├── public/                  served at "/" by Vite (models/*.vrm, animations/*.vrma)
├── infra/                   Docker + deploy (Dockerfile*, docker-compose.yml, nginx.conf, config.yaml)
├── docs/                    AGENTS mirror, ARCHITECTURE.md, PIPELINE.md, CHANGELOG.md (canonical)
├── scripts/                 dev.mjs (reads infra/config.yaml)
├── offline/                 datasets + colab SMPLest-X + motion_analysis (graph/EEMGM)
├── packages/                future shared packages (core, avatar, skeleton placeholders)
├── AGENTS.md                this file (canonical at root, mirrored in docs)
├── README.md                Normal (5173) + Docker (80) + restart
└── config.yaml              universal config (also in infra/, env overrides)
```

### 2.3 Architectural contracts — these are load-bearing

1. **`AvatarController` is the only public class of the avatar module.** Consumers import from `frontend/avatar/index.ts` (the barrel), never from deep paths like `../avatar/animation/AnimationController`.
2. **`@pixiv/three-vrm` is confined** to `VrmLoader`, `VRMAGestureLoader`, and the two private adapter factories inside `AvatarController`. `AnimationController` and `ExpressionController` must stay VRM-free — they see only the injected `HumanoidRig` / `ExpressionBackend` interfaces.
3. **`frontend/main.ts` is a composition root.** It constructs and wires modules. It must contain no rendering, loading, animation, or business logic.
4. **Gestures are data-driven.** Adding a sign = drop a `.vrma` into `public/animations/` + add ONE entry to `data/motion_manifest.json` (and `backend/vocabulary.json` via `offline/tools/generate_vocab_manifest.py`). No code changes.
5. **Frame order matters:** `animation.update(delta)` must run *before* `vrm.update(delta)` — the mixer animates normalized bones, then the VRM copies them onto the raw skeleton. Do not reorder.
6. **`GestureCommand` is the AI boundary.** It is a serializable intent DTO; keep it free of Three.js types.
7. **The SkeletonStream is the universal motion format.** `frontend/skeleton/` is VRM-free and the interchange contract between capture and renderer. Renderers (neon viewer, VRM avatar) consume `SkeletonStream` through the `SkeletonRenderer` interface; nothing outside `frontend/avatar/**` may import `@pixiv/three-vrm`, and no renderer may re-derive coordinate conventions (`toViewSpace` in `SkeletonStream.ts` owns Y-up / root-centering / scaling — once).

### 2.4 Runtime contract

- Backend: `POST /translate`, body `{"text": "hello"}` → `{"gloss": ["HELLO"], "segments": [...]}`. Requires `1 ≤ len(text.strip()) ≤ 500` else `422`. `GET /health` → `{"status":"ok"}`, `GET /ready` → `{"status":"ready"}` or `503`.
- Frontend (`frontend/main.ts`) calls `VITE_API_URL/translate` if set, else `/api/translate` (Vite proxy `frontend/vite.config.ts` in dev, `infra/nginx.conf` in prod). CORS from `FRONTEND_ORIGIN` (default `http://localhost:5173,http://127.0.0.1:5173`). Both: `npm --prefix frontend run dev` (5173) and `python -m backend.app` or `uvicorn backend.app:app` from repo root (or `docker compose -f infra/docker-compose.yml up`).
- Gloss and gesture ids are identical by convention; `backend/mapper.py` is the seam where they diverge; `data/motion_manifest.json` is single source.

### 2.5 Known-broken state

`npx tsc --noEmit` now 0, `npm --prefix frontend run build` 3 chunks (was 44 errors in `src/motion/motion_manifest.ts` before rename to `.json`). No known broken state — tree is green. If `npx tsc` fails, fix is load-bearing.

Historical rot already removed: `HANDOVER.md`, `frontend/venv/`, `Please.vrma`/`hello_sign.vrma` orphans, `public/models/avatar.vrm` dup (14 MB). `dist/` is build output, `.venv` at root.

---

## 3. Rules for agentic coding

### Before you edit

1. **Read the file before changing it.** Never edit from memory or from a summary.
2. **Verify claims by running commands, not by inference.** `npx tsc --noEmit` is the source of truth for build health, not the dev server and not this document.
3. **Treat `HANDOVER.md` as untrusted.** If it conflicts with the code, the code wins.
4. **Check `data/motion_manifest.json`.** It is the single source for gloss → motion; `GestureRegistry` and `MotionCatalog` both read it. Changing a sign usually means changing this file and `backend/vocabulary.json` via `offline/tools/generate_vocab_manifest.py`.

### While you edit

5. **Respect the module boundaries in §2.3.** If a change seems to require importing `@pixiv/three-vrm` into `AnimationController`, or importing a deep avatar path from outside the module, the design is telling you to route it through `AvatarController` instead.
6. **Match the surrounding style.** This codebase uses 2-space indent in `frontend/avatar/**`, explicit `readonly` on injected fields, `private` methods below public ones, and doc comments that explain *why a class exists*, not what each line does. Match the density you find in the file you are editing.
7. **Keep the requested scope.** Fix what was asked. Do not opportunistically refactor, reformat, rename, or "clean up" adjacent code. Note unrelated problems in your reply instead of fixing them.
8. **No new dependencies** without asking. The dependency list is deliberately small.
9. **Do not touch `dist/`.** It is build output. Regenerate it with `npm --prefix frontend run build`.
10. **Do not commit or push** unless explicitly asked. This directory is not currently a git repository.
11. **Prefer deleting dead code over commenting it out.**
12. **Assets are binary and large.** Never rewrite, truncate, or "regenerate" a `.vrm` or `.vrma` file. Only add, move, or reference them.

### After you edit

13. **Type-check before reporting done:** `npx tsc --noEmit`. Report the actual error count, including errors you did not introduce.
14. **Report failures honestly.** If a check fails or you skipped a step, say so plainly with the output. Never describe unverified work as working.
15. **State what you did not do.** If part of the task was blocked, finish everything else and name the gap explicitly.

### Backend specifics

16. `recognizer.py` returning `[text]` is a known stub, not a bug to silently patch — real tokenization changes translation behaviour and should be a deliberate, discussed change.
17. Keep `dictionary.json` keys **lowercase and punctuation-free** — `normalizer.py` lowercases and strips punctuation before lookup, so any other casing is dead.
18. Gloss values in `dictionary.json` must match ids in `GestureManifest.ts` exactly (uppercase), or the sign silently fails to play.

---

## 4. Common commands

```bash
# Frontend
npm --prefix frontend install
npm --prefix frontend run dev              # Vite dev server on :5173 (does NOT type-check)
npx tsc --noEmit                           # type-check — the real build gate (reads frontend/tsconfig.json)
npm --prefix frontend run build            # tsc && vite build (both pages: index + skeleton-viewer)
# or from frontend/: npm install && npm run dev
```

Skeleton debug viewer (no VRM, no backend): with `npm --prefix frontend run dev` running, open
`http://localhost:5173/skeleton-viewer.html`. It plays a serialized
`source_skeleton.v1` stream from `public/skeleton/hello.json` (override with
`?src=/path.json`).

```bash
# Backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # universal at root, backend/ delegates there
python -m uvicorn backend.app:app --reload --port 8000  # from repo root
# or: cd backend && uvicorn app:app --reload
# Docker: docker compose -f infra/docker-compose.yml up --build (frontend :80, backend :8000)
```

---

## 5. Change log rule

Create a file named `docs/CHANGELOG.md` (also mirrored from `CHANGELOG.md` at root for `tsc` include). **Every time a file is modified, update `CHANGELOG.md` in the same turn as the modification.**

Each entry must record the date, the file(s) touched, what changed, and why:

```markdown
## YYYY-MM-DD

### `path/to/file.ts`
- What changed, in one line.
- Why it changed.
```

This applies to every file edit, creation, deletion, or rename — no exceptions. If you modify several files for one task, group them under a single dated entry. Do not batch the log update for later; write it before reporting the task complete.
