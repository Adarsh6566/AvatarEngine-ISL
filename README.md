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

---

# Running the pipelines

There are three apps. **Read this table first — it is the thing people get wrong.**

| | URL | Needs backend? | Needs Vite? |
|---|---|---|---|
| **Pipeline 1** — `.vrma` signing | `http://localhost:5173/` | **YES** (`:8000`) | yes (`:5173`) |
| **New pipeline** — captured motion | `http://localhost:5173/signer.html` | **no** | yes (`:5173`) |
| **Pipeline 2** — video → skeleton | `http://localhost:8001/` | is its own server | no |

> **The most common failure:** you start only Vite, open `localhost:5173/`, and
> pipeline 1 loads but nothing signs. The page is served by Vite, but every
> translation goes to the backend on `:8000`. No backend, no signing. The new
> pipeline has no backend at all, so it keeps working — which makes it look like
> "only the signer runs."
>
> Check with: `curl -s http://127.0.0.1:8000/health` → expect `{"status":"ok"}`.

## One-time setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -r pipeline/requirements.txt
npm --prefix frontend install
```

---

## Pipeline 1 — text → `.vrma` signing

Needs **two** servers. This one command starts both as a single process group
(Ctrl+C stops both):

```bash
npm run dev:all
```

Open **http://localhost:5173/**

Two terminals instead, if you want separate logs:

```bash
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
```

```bash
npm --prefix frontend run dev
```

Knows 26 words → 9 word signs (`hello`, `please`, `sorry`, `yes`, `no`, `me`,
`you`, `bye`, `thanks`…). Anything else is fingerspelled letter by letter.
Try `hello please yes`.

Verify the backend independently of the browser:

```bash
curl -s -X POST http://127.0.0.1:8000/translate -H 'Content-Type: application/json' -d '{"text":"hello please"}'
```

Expect `{"gloss":["HELLO","PLEASE"],...}`.

---

## New pipeline — text → captured motion

Needs **only** Vite. No backend, no `.vrma`.

```bash
npm --prefix frontend run dev
```

Open **http://localhost:5173/signer.html**

(If `npm run dev:all` is already running, this page is served too — just open
the URL. Do not start a second Vite; the port is taken.)

| Type | Performs | Captured from |
|---|---|---|
| `hello` / `hi` / `hey` | `HELLO` | `MVI_0029.MOV` |
| `alright` / `okay` / `ok` | `ALRIGHT` | `MVI_0037.MOV` |
| `good morning` / `morning` | `GOOD_MORNING` | `MVI_0042.MOV` |
| `good afternoon` / `afternoon` | `GOOD_AFTERNOON` | `MVI_0046.MOV` |
| `how are you` | `HOW_ARE_YOU` | `MVI_0033.MOV` |

Phrases match longest-first, so `good morning` is **one** sign. Words with no
captured sign are skipped — there are no letter clips here, so it cannot
fingerspell.

Finger jitter is tunable live, no code edit:

```
http://localhost:5173/signer.html?smooth=0.93
```

`0` disables damping, values approaching `1` damp harder but make the fingers
trail the wrist. Default `0.9`. The active value is logged on load.

---

## Pipeline 2 — video → skeleton → avatar

Its own server, independent of the other two.

```bash
.venv/bin/python -m uvicorn pipeline.app:app --host 127.0.0.1 --port 8001 --reload
```

Open **http://localhost:8001/**, drop a video, press **Run**. Three panes:
source video, skeleton, VRM mirroring the motion. Outputs land in
`pipeline/outputs/`.

From the command line:

```bash
curl -s -X POST "http://127.0.0.1:8001/api/extract?space=world&extractor=mediapipe" -F "file=@offline/datasets/isl_greeting/hello/MVI_0029.MOV" -o out.json
```

Extractors: `mediapipe` (default, body + fingers), `yolo` (body only),
`hybrid_yolo_mediapipe`. The two `smplx` options return **501** — not
implemented, they need model weights.

---

## Running all three at once

```bash
npm run dev:all
```

```bash
.venv/bin/python -m uvicorn pipeline.app:app --host 127.0.0.1 --port 8001 --reload
```

Two terminals, three apps: `localhost:5173/`, `localhost:5173/signer.html`,
`localhost:8001/`.

---

## Opening it on your phone

Bind Vite to all interfaces:

```bash
npm --prefix frontend run dev -- --host 0.0.0.0
```

Vite prints several `Network:` URLs — pick the one matching your Wi-Fi adapter
(`ipconfig getifaddr en0`). Open `http://<that-ip>:5173/signer.html`.

Pipeline 1 works over the network too: the browser talks to Vite, and Vite
proxies `/api` to the backend on localhost, so the backend does **not** need
`--host` and CORS never comes into play.

Requirements: phone and Mac on the same Wi-Fi; macOS firewall must allow
incoming connections for `node`; guest networks with client isolation will block
it silently.

---

## Adding a sign to the new pipeline

**1.** Extract (pipeline 2 running):

```bash
curl -s -X POST "http://127.0.0.1:8001/api/extract?space=world&extractor=mediapipe" -F "file=@offline/datasets/isl_greeting/how_are_you/MVI_0033.MOV" -o /tmp/raw.json
```

**2.** Write the stream out as a sign asset:

```bash
python3 -c "import json; r=json.load(open('/tmp/raw.json')); s=r['stream']; s['meta']['gloss']='HOW_ARE_YOU'; json.dump({'meta':s['meta'],'frames':s['frames']}, open('public/skeleton/how_are_you.json','w'))"
```

**3.** Add one line to `frontend/signer/SignLibrary.ts`:

```ts
{ gloss: 'HOW_ARE_YOU', path: '/skeleton/how_are_you.json', words: ['how are you'] },
```

No manifest, no vocabulary, no backend reload.

---

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -t .
```

> Reports **one expected failure**: digits `0`–`9` exist in
> `backend/language/alphabet.json` but have no manifest entry, so they caption
> without animating. Known gap, not a regression.

---

## If a port is taken

`BACKEND_PORT` is read by the backend, by `vite.config.ts` (for the `/api`
proxy) and by `scripts/dev.mjs`, so one variable moves everything:

```bash
BACKEND_PORT=8010 npm run dev:all
```

To make it permanent, set `backend.port` in `config.yaml`. Find the holder:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

## Gotchas

- **Vite may bind IPv6 only**, so `localhost:5173` works but `127.0.0.1:5173`
  does not. Force IPv4 with `npm --prefix frontend run dev -- --host 127.0.0.1`.
- **A backgrounded browser tab throttles `requestAnimationFrame`**, so a sign
  appears to hang until you switch back to it. Normal browser behaviour.
- **Pipeline 2 has no upload size limit** and never prunes `pipeline/outputs/`.
- **Skeleton assets are ~300-400 KB each**, fetched on demand. `.vrma` clips are
  all preloaded at boot by pipeline 1.
