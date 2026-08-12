# avatar-engine

An Indian Sign Language avatar. Type English text, and a 3D VRM avatar signs it — falling back to fingerspelling for words it has no sign for.

```
  Text  ──►  Backend (FastAPI)  ──►  Gestures  ──►  Frontend (three.js + VRM)
             recognise → map           HELLO           avatar signs, caption
             → fingerspell             LETTER_H…       follows along
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
