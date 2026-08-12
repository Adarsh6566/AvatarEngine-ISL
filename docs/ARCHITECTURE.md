# Architecture Notes

Running record of deliberate structural decisions and the trade-offs behind
them. Add a section when a choice isn't obvious from the code alone.

---

## Gesture / motion metadata: one source, neutral location

**Decision.** All gesture metadata (gloss id → asset path, plus `motionId`,
`duration`, `dataset`, …) lives in a single file, **`data/motion_manifest.json`**.
That file is a *leaf*: it imports nothing. Both feature modules read it directly (frontend `frontend/motion` + `frontend/avatar` now depend on `data`, not on each other).

```
                  data/motion_manifest.json  ← data leaf, owned by neither module (not inside frontend)
                      ▲                     ▲
       (reads)        │                     │       (reads)
   src/motion/MotionCatalog        src/avatar/gestures/GestureRegistry
   (gloss → motion, for the        (manifest → {id, url}, for clip
    Sequencer/translator path)      registration in AvatarController)

   Runtime drive path (high → low, through the avatar's PUBLIC api):
   Sequencer → MotionPlayer ──► src/avatar (AvatarController.playGesture)
```

**Dependency rule.**
- ✅ `motion → avatar`: the motion pipeline orchestrates the avatar through the
  `src/avatar` public API (`MotionPlayer` → `AvatarController`). High-level drives
  low-level. This is the natural direction.
- ✅ `motion → data` and `avatar → data`: both read the shared manifest in `data`.
- ❌ `avatar → motion`: the avatar module must **not** import from `src/motion`.
  Keep `src/avatar` self-contained (see its `index.ts` charter).

**How we got here.**
1. Originally there were *two* sources of gesture id→url metadata: a hand-written
   `GESTURE_MANIFEST` array inside `src/avatar/`, and `src/motion/motion_manifest.json`.
   They drifted — the `S` letter pointed at `S_sign.vrma` in one and the real
   `s_sign.vrma` in the other. Latent bug, waiting to bite.
2. Consolidated to a single source (`GestureRegistry` reads the JSON; the array
   and `GestureManifest.ts` were deleted).
3. That first cut put the manifest in `src/motion/`, so `src/avatar` imported from
   `src/motion` — while `src/motion` already imported from `src/avatar`. Bidirectional
   module coupling, and it broke the avatar module's self-containment.
4. Moved the manifest to a neutral `src/data/` so neither module owns the other's
   data. Both now depend *downward* on the leaf; the cycle is gone.
5. Moved `src/data/` → `packages/data/` → `data/` so data is not inside frontend — `frontend/` (`frontend/`) and `data/` (`data/`) are correctly named top-level modules and not duplicated. Backend `config.yaml` `dictionary.manifest_path` now points to `data/motion_manifest.json`.

**Trade-off accepted.** Single-source removes drift but makes the manifest
**load-bearing for the avatar**: a typo in `motion_manifest.json` (the file edited
every time a word is added) can now break avatar clip loading, where before the
avatar had its own controlled list. We judged killing the drift class of bug worth
the wider blast radius. If `src/avatar` is ever split into a standalone package,
revisit whether it should carry its own manifest again.
