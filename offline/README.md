# Offline Motion Pipeline

Converts real ISL RGB videos into avatar-ready **VRMA motion assets**, entirely
offline. This is the **producer**; the app under `src/` + `backend/` is the
**consumer**. They share no code — only two file contracts:

1. a valid `.vrma` clip, and
2. a `motion_manifest.json` entry.

## How it differs from the runtime
| | Runtime (`src/`, `backend/`) | Offline (`offline/`) |
|---|---|---|
| Language | TypeScript / Python (FastAPI) | Python (batch scripts) |
| When | live, per request | ahead of time, per dataset |
| Imports runtime code | — | **never** |
| Output | rendered avatar | `.vrma` + manifest fragment |

The offline pipeline **never edits runtime files**. `tools/register` only prints
a merge-ready manifest fragment; a human applies it.

## Expected workflow
```
datasets/<name>/raw/*.mp4
  → ingest → extract_pose → reconstruct → normalize → retarget → export_vrma
  → output/vrma/*.vrma  +  output/manifest/*.json
  → (human) copy to public/animations/ and merge into src/data/motion_manifest.json
```

## Status & roadmap (2026-08-11)
- **Foundation + MediaPipe path**: DONE — `offline/output/` already contains 5-sign greetings artifacts: `vrma/hello_isl.vrma`, `animations/`, `manifests/`, `source_skeleton/`, `target_motion/` (see `offline/output/README` if present). Validated on `MVI_0029.MOV` (25 FPS, 63 frames checked).
- **SMPLest-X path (Phase 2)**: EXPORTER VERIFIED (`offline/colab/export_smplestx_npz.py` collects all 9 tensors: `smplx_root_pose`…`smplx_joint_cam`, 165-dim, single-person abort, finite checks). Real CUDA inference **pending** — must run in Colab (T4, `smplest_x_h` checkpoint) to produce `offline/output/smplx/isl_hello_MVI_0029.npz` (see `offline/output/smplx/README.md` + `offline/tools/validate_npz.py`).
- Next: Phase 2 real inference → Phase 3 graph → Phase 4-5 matching/EEMGM. See `DESIGN.md` and `backend/implementations/Phase*.txt` (now 5 compressed phases).
