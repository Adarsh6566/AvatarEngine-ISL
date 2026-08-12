# infra — deployment

Mirrors root `Dockerfile`, `docker-compose.yml`, `nginx.conf`, `config.yaml`, `requirements.txt`, `.env.example`.
Root keeps canonical copies for `run.sh` + `backend/config.py` (which looks for `../config.yaml`). `infra/` is the future single place; root files will be removed after `vite.config` + `scripts/dev.mjs` switch to `infra/config.yaml`.
