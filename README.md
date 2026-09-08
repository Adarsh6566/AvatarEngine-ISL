# avatar-engine

An Indian Sign Language avatar, in three parts:

1. **Text → sign (authored)** — type English text and a 3D VRM avatar signs it, using hand-authored `.vrma` clips and falling back to fingerspelling for words it has no sign for.
2. **Text → sign (captured)** — the same avatar and text bar, but every sign is skeletal motion captured from real ISL video. No `.vrma`, no fingerspelling, no backend.
3. **Video → skeleton** — the motion-capture pipeline that produces those captured signs: drop in a video, MediaPipe extracts pose + hands, and the motion retargets live onto the avatar.

```
  Text  ──►  Backend (FastAPI)  ──►  Gestures  ──►  Frontend (three.js + VRM)
             recognise → map           HELLO           avatar signs, caption
             → fingerspell             LETTER_H…       follows along

  Video ──►  pipeline (MediaPipe) ──►  skeleton JSON ──►  VRM avatar signs
             pose + hands 2.5D          source_skeleton.v1   arms · hands · fingers
```

---

## Requirements

- **Node 18+** and **Python 3.11 or 3.12** (3.13 works, but MediaPipe wheels are patchier)
- **Docker Desktop** only if you use the Docker path
- Windows, macOS, or Linux

---

## First-time setup

Run once. Everything after this is just starting servers.

**Windows (PowerShell)**

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r pipeline\requirements.txt
npm --prefix frontend install
```

**macOS / Linux**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -r pipeline/requirements.txt
npm --prefix frontend install
```

> Tunables live in `config.yaml` — ports, CORS, validation, animation, playback speeds. Env vars override it; see `.env.example`.

---

## Running it

Each pipeline is a separate server. Run them from the repo root, one per terminal tab.

### Pipelines 1 & 2 — the avatar and its text bar

These two share a frontend, so one Vite server serves both. Only pipeline 1 needs the backend.

**Terminal 1 — backend (pipeline 1 only)**

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
```

**Terminal 2 — frontend (both pipelines)**

```powershell
npm --prefix frontend run dev
```

On macOS/Linux the backend line is `.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload`; the frontend line is identical.

Or start both at once, in a single tab — `Ctrl+C` stops both:

```powershell
npm run dev:all
```

| URL | Pipeline | Needs backend? |
|---|---|---|
| http://localhost:5173/ | **1** — authored `.vrma` clips, with fingerspelling | yes, `:8000` |
| http://localhost:5173/signer.html | **2** — captured motion only | **no** |
| http://localhost:5173/skeleton-viewer.html | debug clip player | no |

Because pipeline 2 does its own text matching in the browser, `signer.html` runs with Vite alone — skip Terminal 1 entirely if that's all you need.

### Pipeline 3 — video → skeleton → avatar

Self-contained: its own FastAPI app, serving its own dashboard. No Node, no backend, no Vite.

```powershell
.\.venv\Scripts\python.exe -m uvicorn pipeline.app:app --port 8001
```

Open **http://localhost:8001/**, drop a video, pick an extractor, hit **Run**. Three panes show the source video, the extracted skeleton, and the avatar retargeted live and synced to the video.

Each run writes `<name>.json`, `<name>_skeleton.mp4`, and `<name>_overlay.mp4` into `pipeline/outputs/`, downloadable from the dashboard.

**Extractors.** `mediapipe` (pose + hands) is the default and the one the shipped clips were made with. `hybrid_yolo_mediapipe` uses YOLO for the body and MediaPipe for the hands. The two SMPL-X modes return **501** — they are stubs, and are not wired to run even with the model files present.

**First run downloads models.** The `mediapipe` extractor fetches `pose_landmarker_lite.task` and `hand_landmarker.task` (~13 MB) into `pipeline/.models/` — needs internet once. `hybrid_yolo_mediapipe` does *not* download them: if they are missing it silently runs body-only with no hands, which is useless for sign language. Run `mediapipe` once first, or fetch them yourself:

```powershell
curl -sSL -o pipeline\.models\pose_landmarker_lite.task "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
curl -sSL -o pipeline\.models\hand_landmarker.task "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
```

The 3D panes load `three` / `@pixiv/three-vrm` from a CDN, so the browser needs internet on first load. The avatar model is committed.

### Adding a captured sign

1. Extract the video on `:8001` and download the JSON.
2. Save it as `public/skeleton/<sign>.json`.
3. Add one line to `frontend/signer/SignLibrary.ts`:

```ts
{ gloss: 'GOOD_EVENING', path: '/skeleton/good_evening.json', words: ['good evening', 'evening'] },
```

`words` are the written forms that select the sign; phrases may contain spaces, and the longest phrase always wins, so `good evening` performs one sign rather than `good` + `evening`. Nothing else needs changing — the match window sizes itself from the library.

### Docker

```bash
docker compose up --build   # frontend nginx on http://localhost, backend on http://localhost:8000
docker compose down         # stop and remove containers
```

**Access:** `http://localhost` (nginx serves `dist` and proxies `/api/` → backend). No `:5173` in Docker — that's local Vite only. Custom port: `FRONTEND_PORT=3000 docker compose up --build`.

Rebuild after changing code (`frontend/`, `backend/`, `public/`, `Dockerfile`); for a `config.yaml`-only change, `docker compose restart backend` is enough since it is mounted. Compose waits for `backend` to be healthy (`GET /ready`) before starting the frontend.

---

## Try it

**Pipeline 1** — http://localhost:5173/

| Type this | What happens |
|---|---|
| `hello` | One sign |
| `yes yes no` | Three signs, repeats preserved |
| `hello please. thank you!` | Multiple sentences |
| `please help me` | `help` fingerspells, caption highlights letters |
| `banana` | Fully fingerspelled |

**Pipeline 2** — http://localhost:5173/signer.html

Knows nine captured signs: `hello · alright · good morning · good afternoon · good evening · good night · how are you · thank you · pleased`

| Type this | What happens |
|---|---|
| `good evening` | One sign, not `good` + `evening` |
| `hello thank you` | Two signs in sequence |
| `nice to meet you` | Four-word phrase → `PLEASED` |
| `banana thank you` | Unknown word skipped, no fingerspelling |

Both pages: drag to orbit, scroll to zoom, and the bottom-right button cycles playback **1x → 5x** (from `animation.playback_speeds` in `config.yaml`). `signer.html` also takes `?smooth=0.93` to tune finger smoothing live.

---

## Other commands

```powershell
npm --prefix frontend run dev        # Vite dev (no type-check)
npm --prefix frontend run build      # tsc && vite build (emits dist/)
npm --prefix frontend run preview    # serve dist
```

Type-check — must run from `frontend/`, since that is where TypeScript is installed:

```powershell
cd frontend; npx tsc --noEmit
```

---

## Troubleshooting

**`port 8000/8001/5173 in use`**

```powershell
Get-NetTCPConnection -LocalPort 5173 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

On macOS/Linux: `lsof -ti:5173 | xargs kill`.

**`npm` / `node` not recognised** — Node is installed but not on this shell's PATH. Use the full path, or add it for the session:

```powershell
$env:Path = "C:\Program Files\nodejs;$env:Path"
```

**Avatar spins forever on `/`** — the backend is down. Check `curl http://localhost:8000/health` and `/ready`. `signer.html` never needs it.

**`signer.html` says "No captured sign for that"** — the phrase is not in `SignLibrary.ts`. The known list is printed under the input bar.

**Pipeline extracts but the avatar barely moves** — the hand model is missing, so only the body was tracked. See *First run downloads models* above.

**Blank page** — check the browser console. A missing `public/models/AvatarSample_C.vrm` or malformed `config.yaml` logs there.

---

## Project layout

```
├── frontend/               Vite frontend (npm --prefix frontend)
│   ├── index.html          pipeline 1 — authored .vrma clips
│   ├── main.ts             its composition root
│   ├── signer.html         pipeline 2 — captured motion
│   ├── signer/             its composition root + SignLibrary
│   ├── skeleton-viewer.html debug clip player
│   ├── vite.config.ts      three entry points; proxies /api/* → backend
│   └── avatar/, motion/, skeleton/, ui/, core/, config/
├── data/                   motion_manifest.json (pipeline 1 vocabulary)
├── backend/                FastAPI, pipeline 1 only (:8000)
├── pipeline/               video → skeleton dashboard (:8001)
│   ├── app.py              /api/extract, serves its own frontend
│   ├── extractor/          MediaPipe / YOLO extractors, normalize, smooth
│   ├── frontend/           the dashboard
│   └── outputs/            extraction artifacts (gitignored)
├── public/                 models/*.vrm, animations/*.vrma, skeleton/*.json
├── infra/                  Docker + deploy
├── docs/                   ARCHITECTURE.md, PIPELINE.md, CHANGELOG.md
└── config.yaml             universal config (env overrides)
```

### Further reading

| Document | Covers |
|---|---|
| [`backend/PIPELINE.md`](backend/PIPELINE.md) | How text becomes gestures |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Single-source manifest decision |
| [`AGENTS.md`](AGENTS.md) | Architecture and agent rules |
| [`docs/CHANGELOG.md`](docs/CHANGELOG.md) | Every file modification |


Run it yourself in the Zed terminal

Three servers, one per terminal tab, all from the repo root.

Tab 1 — backend (only needed for the .vrma pipeline):

.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload

Tab 2 — frontend (serves both avatar pages):

npm --prefix frontend run dev

Tab 3 — extraction pipeline (fully standalone):

.\.venv\Scripts\python.exe -m uvicorn pipeline.app:app --port 8001

Tab 1 — lecture backend (port 8002)

.\.venv\Scripts\python.exe -m uvicorn lecture.app:app --port 8002

Tab 2 — frontend (port 5173)

npm --prefix frontend run dev
Then:

URL	What
http://localhost:5173/	Pipeline 1 — authored .vrma + fingerspelling
http://localhost:5173/signer.html	Pipeline 2 — your 9 captured signs
http://localhost:8001/	Pipeline 3 — video → skeleton dashboard

Two shortcuts worth knowing: signer.html needs no backend, so if that's all you're working on, skip Tab 1 entirely — Vite alone is enough. And npm run dev:all starts the backend and frontend together in one tab, with Ctrl+C stopping both (I verified the module path it uses actually resolves).

If Zed's terminal says npm isn't recognised, Node is installed but off that shell