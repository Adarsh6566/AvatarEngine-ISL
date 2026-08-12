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
| Build / dev server | Vite 8 (`npm run dev`, `npm run build`, `npm run preview`) |
| Language (frontend) | TypeScript ~6.0, ESM, `noEmit` (Vite bundles; `tsc` type-checks only) |
| 3D | three.js ^0.185, three-stdlib |
| Avatar format | `@pixiv/three-vrm` ^3.5.5 (VRM), `@pixiv/three-vrm-animation` ^3.5.5 (VRMA) |
| Backend | FastAPI 0.116.1, Uvicorn 0.35.0, Pydantic 2.11.7 |
| Python | 3.13 |

### 2.2 Repository layout

```
avatar-engine/
├── index.html                 Vite entry; mounts #app, loads src/main.ts
├── skeleton-viewer.html       second Vite entry — standalone neon-armature debug viewer
├── vite.config.ts             multi-page build input (index + skeleton-viewer)
├── package.json               deps + dev/build/preview scripts
├── tsconfig.json              bundler resolution, noEmit, noUnusedLocals/Parameters
├── AGENTS.md                  this file
├── CHANGELOG.md               modification log (see §5)
├── HANDOVER.md                legacy architecture doc — STALE, do not trust
│
├── public/                    served at "/" by Vite
│   ├── models/avatar.vrm      the avatar (~14 MB)
│   ├── animations/*.vrma      sign clips
│   ├── skeleton/*.json        serialized SkeletonStream artifacts for the viewer
│   ├── favicon.svg, icons.svg
│
├── core/                      shared render infrastructure (VRM-free, avatar-free)
│   ├── RenderEngine.ts        scene, camera, renderer, frame loop
│   ├── Clock.ts               delta time, clamped 0.1s, pausable
│
├── src/
│   ├── main.ts                composition root — wiring only, no logic
│   ├── style.css
│   ├── api/translate.ts       fetch POST /api/translate (VITE_API_URL or Vite proxy)
│   ├── ui/SignControls.ts     vanilla-DOM input + button + status line
│   ├── sign/Sequencer.ts      iterates gloss tokens, plays each in order
│   ├── motion/
│   │   ├── motion_manifest    gloss → { motionId, assetPath, duration }
│   │   ├── MotionCatalog.ts   gloss → MotionReference (throws if unknown)
│   │   ├── DatasetLoader.ts   MotionReference → LoadedMotion
│   │   ├── MotionProcessor.ts LoadedMotion → ProcessedMotion
│   │   └── MotionPlayer.ts    ProcessedMotion → avatar.playGesture()
│   ├── skeleton/              the canonical motion-stream module (VRM-free)
│   │   ├── SkeletonStream.ts  stream contract + loader + Y-up normalization
│   │   ├── SkeletonRenderer.ts hot-swap renderer interface + SkeletonPlayer
│   │   └── NeonLineRenderer.ts three.js LineSegments armature (no VRM)
│   ├── viewer/
│   │   └── skeleton-viewer.ts composition root for skeleton-viewer.html
│   └── avatar/
│       ├── index.ts                        PUBLIC BARREL — the only import path
│       ├── controller/AvatarController.ts  the single public class (facade)
│       ├── loading/VrmLoader.ts            .vrm  → VRM
│       ├── loading/VRMAGestureLoader.ts    .vrma → retargeted AnimationClip
│       ├── animation/AnimationController.ts AnimationMixer + actions
│       ├── animation/GestureLibrary.ts     id → AnimationClip map
│       ├── gestures/GestureManifest.ts     data-only list of gestures + URLs
│       ├── gestures/GestureCommand.ts      { type:'sign', id } intent DTO
│       └── expressions/ExpressionController.ts
│
└── backend/
    ├── app.py                 FastAPI app, POST /translate, GET /health, GET /ready, CORS from FRONTEND_ORIGIN
    ├── schemas.py             TranslateRequest{text: str 1..500} / TranslateResponse{gloss, segments}
    ├── mapper.py              map_recognition() vocabulary lookup (+ legacy map_gloss)
    └── language/
        ├── normalizer.py      lowercase, strip punctuation, collapse whitespace
        ├── recognizer.py      recursive sentence→word splitter + PhraseRecognizer
        ├── translator.py      recognize → map → fingerspell → segment/translate
        ├── alphabet.json      char → gesture (a-z, 0-9)
        ├── vocabulary.json    word → gesture (via mapper)
        └── __init__.py        package marker
```

### 2.3 Architectural contracts — these are load-bearing

1. **`AvatarController` is the only public class of the avatar module.** Consumers import from `src/avatar/index.ts` (the barrel), never from deep paths like `../avatar/animation/AnimationController`.
2. **`@pixiv/three-vrm` is confined** to `VrmLoader`, `VRMAGestureLoader`, and the two private adapter factories inside `AvatarController`. `AnimationController` and `ExpressionController` must stay VRM-free — they see only the injected `HumanoidRig` / `ExpressionBackend` interfaces.
3. **`main.ts` is a composition root.** It constructs and wires modules. It must contain no rendering, loading, animation, or business logic.
4. **Gestures are data-driven.** Adding a sign = drop a `.vrma` into `public/animations/` + add ONE entry to `GestureManifest.ts` (and the motion manifest). No code changes.
5. **Frame order matters:** `animation.update(delta)` must run *before* `vrm.update(delta)` — the mixer animates normalized bones, then the VRM copies them onto the raw skeleton. Do not reorder.
6. **`GestureCommand` is the AI boundary.** It is a serializable intent DTO; keep it free of Three.js types.
7. **The SkeletonStream is the universal motion format.** `src/skeleton/` is VRM-free and the interchange contract between capture and renderer. Renderers (neon viewer, VRM avatar) consume `SkeletonStream` through the `SkeletonRenderer` interface; nothing outside `src/avatar/**` may import `@pixiv/three-vrm`, and no renderer may re-derive coordinate conventions (`toViewSpace` in `SkeletonStream.ts` owns Y-up / root-centering / scaling — once).

### 2.4 Runtime contract

- Backend: `POST /translate`, body `{"text": "hello"}` → `{"gloss": ["HELLO"], "segments": [...]}`. Requires `1 ≤ len(text.strip()) ≤ 500` else `422`. `GET /health` → `{"status":"ok"}`, `GET /ready` → `{"status":"ready"}` or `503`.
- Frontend calls `VITE_API_URL/translate` if set, else `/api/translate` (Vite proxy in dev, reverse-proxy in prod). CORS allowed origins from `FRONTEND_ORIGIN` (default `http://localhost:5173,http://127.0.0.1:5173`). Both servers: `npm run dev` (5173) and `uvicorn app:app --reload` from `backend/` (or `python -m backend.app` from repo root).
- Gloss token strings and gesture ids are currently identical by convention. `mapper.py` exists as the seam where they will diverge.

### 2.5 Known-broken state (as of this file's creation)

Do not assume the tree is green. `npx tsc --noEmit` fails with **44 errors, all in `src/motion/motion_manifest.ts`**:

- `motion_manifest.ts` contains raw JSON with no `export`, so it is not valid TypeScript. `MotionCatalog.ts` imports `"./motion_manifest.json"` — a file that does not exist. Renaming the file to `.json` resolves all 44 errors (verified).
- After that rename, one further error surfaces: `MotionProcessor.ts` reads `motion.id`, but `LoadedMotion` defines `motionId`. At runtime this sends `id: undefined` to `playGesture`.
- `motion_manifest`'s `HELLO` entry points at `/public/animations/hello_sign.vrma`; Vite serves `public/` at `/`, so the correct path is `/animations/hello_sign.vrma`.
- `npm run dev` still appears to work because esbuild strips types without checking them. **A working dev server is not evidence of a working build.**

Other rot, safe to leave unless asked: `public/animations/Hello.vrma` is 0 bytes; `Please.vrma` is an orphan duplicate; `dist/` is a stale Aug-3 build; `frontend/venv/` is an empty stray virtualenv; `HANDOVER.md` describes an older state and is not authoritative.

---

## 3. Rules for agentic coding

### Before you edit

1. **Read the file before changing it.** Never edit from memory or from a summary.
2. **Verify claims by running commands, not by inference.** `npx tsc --noEmit` is the source of truth for build health, not the dev server and not this document.
3. **Treat `HANDOVER.md` as untrusted.** If it conflicts with the code, the code wins.
4. **Check both manifests.** `GestureManifest.ts` (loading) and the motion manifest (lookup) list the same signs in different shapes. Changing a sign usually means changing both.

### While you edit

5. **Respect the module boundaries in §2.3.** If a change seems to require importing `@pixiv/three-vrm` into `AnimationController`, or importing a deep avatar path from outside the module, the design is telling you to route it through `AvatarController` instead.
6. **Match the surrounding style.** This codebase uses 2-space indent in `src/avatar/**`, explicit `readonly` on injected fields, `private` methods below public ones, and doc comments that explain *why a class exists*, not what each line does. Match the density you find in the file you are editing.
7. **Keep the requested scope.** Fix what was asked. Do not opportunistically refactor, reformat, rename, or "clean up" adjacent code. Note unrelated problems in your reply instead of fixing them.
8. **No new dependencies** without asking. The dependency list is deliberately small.
9. **Do not touch `dist/`.** It is build output. Regenerate it with `npm run build`.
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
npm install
npm run dev              # Vite dev server on :5173 (does NOT type-check)
npx tsc --noEmit         # type-check — the real build gate
npm run build            # tsc && vite build (both pages: index + skeleton-viewer)
```

Skeleton debug viewer (no VRM, no backend): with `npm run dev` running, open
`http://localhost:5173/skeleton-viewer.html`. It plays a serialized
`source_skeleton.v1` stream from `public/skeleton/hello.json` (override with
`?src=/path.json`).

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

---

## 5. Change log rule

Create a file named `CHANGELOG.md` in the repository root. **Every time a file is modified, update `CHANGELOG.md` in the same turn as the modification.**

Each entry must record the date, the file(s) touched, what changed, and why:

```markdown
## YYYY-MM-DD

### `path/to/file.ts`
- What changed, in one line.
- Why it changed.
```

This applies to every file edit, creation, deletion, or rename — no exceptions. If you modify several files for one task, group them under a single dated entry. Do not batch the log update for later; write it before reporting the task complete.
