# avatar-engine

An Indian Sign Language avatar. Two halves:

1. **Text → sign** — type English text and a 3D VRM avatar signs it, falling back to fingerspelling for words it has no sign for.
2. **Video → sign** — a motion-capture pipeline that turns a sign-language *video* into skeletal motion (MediaPipe) and retargets it **live onto the same VRM avatar** — the source of the signs the first half plays back.

```
  Text  ──►  Backend (FastAPI)  ──►  Gestures  ──►  Frontend (three.js + VRM)
             recognise → map           HELLO           avatar signs, caption
             → fingerspell             LETTER_H…       follows along

  Video ──►  pipeline (MediaPipe) ──►  skeleton JSON ──►  VRM avatar signs (live retarget)
             pose + hands 2.5D          source_skeleton.v1   arms · hands · fingers
```

---

## Running it

> All tunables live in `config.yaml` (ports, CORS, validation, animation). Env vars override it — see `.env.example`.

### Normal (local)

```bash
# Terminal 1 — backend (from repo root)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2 — frontend (from repo root)
npm --prefix frontend install
npm --prefix frontend run dev              # Vite on http://localhost:5173, proxies /api/* → backend
# or: cd frontend && npm install && npm run dev
```

**Access:** `http://localhost:5173` (frontend `frontend/`). Backend at `http://localhost:8000` (`/health`, `/ready`, `/docs`). Frontend uses `VITE_API_URL` if set, otherwise `/api/*`. `config.yaml` at root (also `infra/config.yaml`) drives ports/CORS.

### Docker

```bash
docker compose up --build   # frontend nginx on http://localhost, backend on http://localhost:8000
docker compose down         # stop and remove containers
```

**Access:** `http://localhost` (frontend, nginx serves `dist` and proxies `/api/` → backend). No `:5173` in Docker — that's local Vite only.

Custom port:

```bash
FRONTEND_PORT=3000 docker compose up --build
# then http://localhost:3000
```

**Restart after file changes:**

```bash
# code changed (src/, backend/, public/, Dockerfile, config.yaml in image)
docker compose up --build        # rebuild and restart
# or
docker compose down && docker compose up --build

# only config.yaml changed (mounted as volume)
docker compose restart backend   # no rebuild needed
```

`docker compose` waits for `backend` to be `healthy` (`GET /ready`) before starting `frontend`. Stop with `Ctrl+C` or `docker compose down`.

---

## Motion-capture pipeline (video → avatar)

A self-contained dashboard that captures a sign-language video and drives the VRM avatar from it. Separate from the text→sign backend above (its own FastAPI app on **port 8001**, everything under `pipeline/`).

```bash
# from repo root — Python 3.11 or 3.12 recommended (works on 3.13)
python3 -m venv .venv
source .venv/bin/activate                 # Windows: .venv\Scripts\activate
pip install -r pipeline/requirements.txt
python -m uvicorn pipeline.app:app --port 8001
```

Open **http://localhost:8001/**, drop a video, hit **Run**. The dashboard shows three panes side by side at **1:1:2**:

| Pane | Shows |
|---|---|
| **Source** | the input video |
| **Skeleton** | the extracted joints (2D canvas or 3D orbit) |
| **Avatar (VRM)** | the signing avatar, retargeted live and synced to the video |

**How it works.** MediaPipe extracts pose + both hands (`source_skeleton.v1`: 4 joints/finger), normalized to an upright, root-centered *view* space. The browser retargets joint **positions → VRM bone rotations** by forward-kinematic swing extraction (`frontend/skeleton/VrmRenderer.ts`, ported to `pipeline/frontend/app.js`).

**Sign-language tuned.** Only the meaningful bones are driven — **arms, hands, fingers**. The body stays **upright and still** (torso, head, and legs are locked; MediaPipe's depth for them is unreliable and they carry no meaning). All joints are still captured in the JSON; they're just not applied to the avatar. On the 5173 viewer you can re-enable them for testing with `?body=1`, `?legs=1`, `?root=torso`.

**Notes for a fresh machine.** First run auto-downloads the MediaPipe models (`pose_landmarker.task`, `hand_landmarker.task`, ~13 MB) into `pipeline/.models/` — needs internet once. The 3D panes load `three` / `@pixiv/three-vrm` from a CDN, so the browser needs internet on first load. The avatar model (`AvatarSample_C.vrm`) is committed in the repo.

**Debug viewer.** The Vite app also serves a standalone skeleton/avatar viewer at `http://localhost:5173/skeleton-viewer.html?src=/skeleton/<clip>.json&renderer=vrm` (drop `renderer=vrm` for the neon skeleton).

---

## Try it

| Type this | What happens |
|---|---|
| `hello` | One sign |
| `yes yes no` | Three signs, repeats preserved |
| `hello please. thank you!` | Multiple sentences |
| `please help me` | `help` fingerspells, caption highlights letters |
| `banana` | Fully fingerspelled |

Drag to orbit, scroll to zoom.

---

## Other commands

```bash
npm --prefix frontend run dev        # Vite dev (no type-check)
npx tsc --noEmit                     # type-check — reads frontend/tsconfig.json
npm --prefix frontend run build      # tsc && vite build (emits dist/)
npm --prefix frontend run preview    # serve dist
```

---

## Requirements

- **Node 18+**, **Python 3.11+**, **Docker Desktop** (for Docker run)
- macOS or Linux.

---

## Troubleshooting

**`port 8000/5173/80 in use`** — `lsof -ti:8000 | xargs kill` or `docker compose down`.

**Avatar spins forever** — `curl http://localhost:8000/health` and `curl http://localhost:8000/ready`; in Docker `docker compose ps` should show `backend (healthy)`.

**Blank page** — browser console. Missing `public/models/avatar.vrm` or bad `config.yaml` logs there.

---

## Project layout

```
├── frontend/               Vite frontend (npm --prefix frontend)
│   ├── package.json        Node deps (was at root)
│   ├── vite.config.ts      root: '.', publicDir: '../public'
│   ├── tsconfig.json       include: [".", "../packages", "../data"]
│   ├── index.html          Vite entry
│   ├── main.ts             composition root
│   └── avatar/, motion/, skeleton/, ui/, config/
├── data/                   motion_manifest.json (single source, was src/data)
├── backend/                FastAPI (python -m uvicorn backend.app:app)
├── pipeline/               video → skeleton → avatar dashboard (uvicorn pipeline.app:app :8001)
│   ├── app.py              FastAPI: /api/extract, serves frontend/ + models/
│   ├── extractor/          MediaPipe / YOLO extractors, normalize, smooth, schemas
│   ├── frontend/           static dashboard (index.html, app.js, style.css, models/*.vrm)
│   └── requirements.txt    isolated deps (fastapi, mediapipe, opencv…)
├── public/                 models/*.vrm, animations/*.vrma (served at "/")
├── infra/                  Docker + deploy (Dockerfile*, docker-compose.yml, nginx.conf, config.yaml)
├── docs/                   ARCHITECTURE.md, PIPELINE.md, CHANGELOG.md
├── offline/                datasets + colab SMPLest-X + motion_analysis
├── packages/               future shared packages (core, avatar, skeleton placeholders)
├── AGENTS.md               agent guide (canonical)
├── README.md               Normal + Docker + restart
└── config.yaml             universal config (env overrides)
```

### Further reading

| Document | Covers |
|---|---|
| [`backend/PIPELINE.md`](backend/PIPELINE.md) | How text becomes gestures |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Single-source manifest decision |
| [`AGENTS.md`](AGENTS.md) | Architecture and agent rules |
| [`docs/CHANGELOG.md`](docs/CHANGELOG.md) | Every file modification |
