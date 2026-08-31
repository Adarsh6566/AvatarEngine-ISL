# Changelog

Every file modification in this repository is recorded here. See `AGENTS.md` §5.

---

## 2026-08-21 — new pipeline: loading spinner and 1x-5x speed control

Brought the two UI affordances the `.vrma` app has across to the signer, by **reusing the same components** rather than reimplementing them — both are generic DOM widgets with no coupling to pipeline 1's logic.

### `frontend/signer/main.ts`
- Imports and mounts `ui/ActivityIndicator` and `ui/PlaybackSpeedControl`.
- Spinner shows while the VRM loads at boot, and while a skeleton stream is fetched on first use (streams are 300-400 KB and fetched on demand). Wrapped in `try/finally` so a failed fetch still hides it; cache hits return before it is shown.
- Added a `playbackRate` variable applied to the cursor advance: `cursor += delta * fps * playbackRate`. Speeds come from `config.yaml` (`animation.playback_speeds`) via `APP_CONFIG`, so both pipelines cycle the same 1x → 5x → 1x steps.

### `frontend/signer.html`
- Added `.activity`, `.activity__spinner`, `@keyframes activity-spin` and `.speed-control` styles copied from `style.css` so the signer keeps its self-contained stylesheet while looking identical to the other app. Accent colour bound to the signer's `--accent`.
- Added a `prefers-reduced-motion` rule slowing the spinner, matching pipeline 1.
- **Fixed a collision found during testing:** the speed control is `fixed` bottom-right while the `knows:` hint spans the bar, so below ~820 px the hint ran underneath the button (measured 56 px overlap at 512 px wide). Added `@media (max-width: 820px) { .bar__hint { padding-right: 92px } }`. Pipeline 1 never had this because its bar has no hint line.

### Verification
- `npx tsc --noEmit` exit 0.
- Speed control measured against the 3.24 s `how are you` clip, cache warm so this is playback not fetch:

  | label | measured | expected |
  |---|---|---|
  | 1x | 3.24 s | 3.24 |
  | 2x | 1.65 s | 1.62 |
  | 3x | 1.08 s | 1.08 |
  | 4x | 0.83 s | 0.81 |
  | 5x | 0.66 s | 0.65 |

  Cycles back to 1x after 5x.
- Spinner verified: hidden at rest (`opacity 0`), `opacity 1` with `animation-name: activity-spin` and the accent border when active, positioned 20 px from the top-right.
- Hint/button clearance: 1280 px → no padding applied, text ends 254 px clear; 375 px → 92 px padding applied, text ends 36 px clear.

### Noticed, not changed
The signer shows the VRM's raw **T-pose** until the first sign plays. Pipeline 1 avoids this via `AvatarController.applyNaturalPose()`; the signer deliberately applies no pose, because `captureRest()` must measure the T-pose. Fixing it means posing *after* the capture — a small addition, but out of scope for this change.

---

## 2026-08-21 — README: make the two-server requirement for pipeline 1 explicit

### `README.md`
- Rewrote "Running the pipelines". The table now states, per app, **whether it needs the backend** — the fact that was missing and that caused a real confusion: starting only Vite makes pipeline 1's page load while nothing signs, because every translation goes to `:8000`. The new pipeline has no backend, so it keeps working, which makes it look like "only the signer runs".
- Added that failure as a call-out with the one-line check (`curl -s http://127.0.0.1:8000/health`).
- Added: a "running all three at once" section (two terminals, three apps); phone access via `--host 0.0.0.0`, noting the backend does **not** need `--host` because the browser talks to Vite and Vite proxies `/api` server-side, so CORS never applies; the `?smooth=` finger-damping override; `how are you` in the sign table; and the rAF-throttling gotcha for backgrounded tabs.

---

## 2026-08-21 — new pipeline: viewport-aware avatar framing for portrait screens

On a phone-shaped viewport the avatar's feet sat behind the input bar and the caption crowded the head. The caption and input bar are `position: fixed` over the canvas, so on a tall narrow screen they cover a far larger fraction of the height than they do on a desktop window — roughly a third rather than a seventh.

### `frontend/signer/main.ts`
- Extracted `DESKTOP_DISTANCE` (4.6), `DESKTOP_TARGET_Y` (1.2) and `CAMERA_RISE` (0.15) as named constants; the `RenderEngine` camera and the OrbitControls target now build from them instead of repeating literals.
- Added `frameCamera()`: **measures** the live heights of `.bar` and `.caption`, derives the usable vertical band between them, and computes the camera distance and look-at that fit the avatar (world extent 0.15 → 2.05, plus 8% breathing room) inside that band, centring it on the band rather than on the viewport.
- Added `captionReserve()`: measures the caption while temporarily holding the **longest phrase in the library**, so the reserve is the worst case. Measuring the live caption instead would move the camera mid-sign, since the caption is empty when idle and grows when a sign starts.
- Blending is on **aspect ratio**, not a pixel breakpoint: `t = clamp((1.2 - aspect) / (1.2 - 0.6), 0, 1)`. At aspect ≥ 1.2 `t` is 0 and the desktop framing is used verbatim; at ≤ 0.6 the fitted framing is used; between, it interpolates. Distance is clamped so it can only ever move the camera **back**, never closer than desktop.
- Re-frames on container resize via `ResizeObserver`, falling back to a `window` resize listener.
- Moved the `captionRoot` declaration up beside the other UI lookups. Left where it was, `frameCamera()`'s init call hit it in the temporal dead zone — `ReferenceError: Cannot access 'captionRoot' before initialization` — which threw during module evaluation, so `engine.start()` never ran and the canvas stayed empty. Caught during testing.
- Added a non-nullable `container` alias for `#app`, since TypeScript does not carry the null-narrowing into the `frameCamera` closure.

### Not changed
VRM, retargeting, animation timing, backend, CSS, and pipeline 1 — all untouched.

### Verification
- `npx tsc --noEmit` exit 0.
- **1280×800** (aspect 1.60): blend `t = 0`, framing identical to before at 4.6 / 1.2 — desktop preserved by construction, not by eye.
- **375×812** (aspect 0.46): whole avatar visible; boots end ≈625 px with the bar top at 657, caption ends at 116 with the head top ≈150 — roughly 32 px clear at both ends.
- **430×932** (aspect 0.46): whole avatar visible; boots end ≈723 px with the bar top at 777 — ≈54 px clear.
- Signing verified at each size; no horizontal overflow (`body.scrollWidth` equals viewport width).

### Known, deliberately left alone
On a **short desktop window** (e.g. 1280×800, aspect 1.6) the feet still tuck behind the input bar, exactly as before this change — the brief was to preserve desktop. Removing the aspect blend would fit the avatar at every aspect, at the cost of altering the desktop framing.

---

## 2026-08-21 — new pipeline: finger smoothing raised to 0.9, tunable via URL

`fingerSmoothing: 0.7` was still visibly jittery on `how are you`. Re-measured on a wider bone set and raised the default.

### Where the noise actually is (measured, not assumed)
- It is **not** concentrated in depth. Frame-to-frame change on `rIndex1→rIndex2` splits **X 35% / Y 40% / Z 25%**, so damping one axis (as `smooth.py` does for the spine) would not help.
- The real cause is scale: those finger segments are only **0.013–0.016** view units long while jittering **~0.002 per frame** — a ~15% perturbation on a short vector. `normalize()` converts that into a large angular swing, which is why short bones flail and long ones (arms) do not.

### `frontend/signer/main.ts`
- Default `fingerSmoothing` **0.7 → 0.9**. Measured across 5 right-hand finger bones over 400 frame transitions, counting frames that jump more than 10°:

  | fingerSmoothing | mean °/frame | worst | frames >10° |
  |---|---|---|---|
  | 0.7 | 4.21 | 31.4° | 38 / 400 |
  | 0.85 | 2.73 | 17.9° | 11 / 400 |
  | **0.9** | **2.39** | **14.6°** | **5 / 400** |
  | 0.93 | 1.80 | 9.2° | 0 / 400 |

  0.9 removes ~87% of the visible spikes. Beyond that the fingers begin trailing the wrist — at 25 fps the blend settles over roughly `1/(1-s)` frames.
- Added a URL override, `?smooth=` (accepts 0 to <1, falls back to the default on anything invalid), and a startup log of the active value, so the trade-off can be judged by eye without a code edit.

### Verification
- `npx tsc --noEmit` exit 0.
- Playback rate unaffected by damping: `how are you` completes in 3.27 s and 3.20 s against a 3.24 s clip; `hello` in 2.53 s against 2.52 s.
- Note for future measurement: a **backgrounded tab throttles `requestAnimationFrame`**, so timings taken while the tab is not fronted are meaningless (one such run read 10.19 s for a 3.24 s clip).

---

## 2026-08-21 — new pipeline: full finger articulation with damped rotation

`fingerMode: 'prox'` (previous entry) fixed the flailing by dropping two bones per finger, but the hands read as stiff — and handshape carries meaning in ISL. Restored full articulation and attacked the noise at the rotation level instead.

### `frontend/avatar/animation/SkeletonRetargeter.ts`
- Added `fingerSmoothing` to `RetargetOptions` (default **0** — `VrmRenderer` and the viewer are unaffected), a `prevLocal` map, and `reset()`.
- When `fingerSmoothing > 0`, each finger bone's local rotation is slerped toward the previous frame's by that factor before being written. Arms and torso are untouched: their segments are long enough that direction is stable.
- `reset()` clears the history so a new clip does not start dragged toward the previous clip's final pose.

### `frontend/signer/main.ts`
- `{ fingerMode: 'full', fingerSmoothing: 0.7 }`; `retargeter.reset()` on each new sign.
- 0.7 chosen from measurement, not taste. Frame-to-frame rotation change across right index proximal, middle proximal and index intermediate on `how_are_you`:

  | fingerSmoothing | mean °/frame | worst single-frame jump |
  |---|---|---|
  | 0 (off) | 7.69 | **72.4°** |
  | 0.4 | 5.32 | 51.7° |
  | 0.55 | 5.17 | 36.2° |
  | ~~0.7~~ (superseded — still visibly jittery) | 3.67 | 25.4° |
  | 0.8 | 3.44 | 20.9° |
  | 0.88 | 2.31 | 12.7° |

  72° in a single 40 ms frame is the flailing. Higher factors damp further but settle slower: at 25 fps, 0.88 takes ~0.33 s and mutes fast handshape changes, whereas 0.7 settles in ~0.13 s.

### Verification
- `npx tsc --noEmit` exit 0.
- `hello` completes in 2.53 s (2.52 s clip), `how are you` in 3.27 s (3.24 s clip) — playback rate unaffected by the damping.
- Open question for the author: whether 0.7 still shows residual jitter on the fastest handshape transitions. If so the next lever is the capture itself — `pipeline/extractor/smooth.py` currently uses `alpha 0.45` for FINE joints — rather than more rotation damping.

---

## 2026-08-21 — new pipeline: fix HELLO signing backwards, damp finger noise

Two reported defects: HELLO's arm bent backwards as if signing behind the avatar, and HOW_ARE_YOU's fingers moved unnaturally as the right arm rose. Both diagnosed from the data.

### `public/skeleton/hello_captured.json` (new)
- Re-captured `MVI_0029.MOV` through `pipeline.app` (`mediapipe`, `space=world`): 63 frames @ 25 fps, 289 KB, pipeline dialect.
- **Root cause of the backwards arm:** `public/skeleton/hello.json` is the old offline artifact in raw `mediapipe_image_normalized` space. `SkeletonStream.toViewSpace()` flips **Y** (`space` contains "Y down") but **never touches Z**, whereas `pipeline/extractor/normalize.py` flips Z for world-space captures ("mediapipe world Z is mirrored vs Three.js right-handed"). So HELLO alone never received the depth correction the other four signs did, and its entire arm chain was mirrored in Z.
- Measured at the peak frame of the wave — same pose, inverted depth:

  | | shoulder Z | elbow Z | wrist Z | elbow angle |
  |---|---|---|---|---|
  | old `hello.json` | −0.176 | −0.494 | −0.942 | 111.1° |
  | new `hello_captured.json` | +0.158 | +0.380 | +0.744 | 112.4° |

  Mean Z(rWrist − rShoulder) went from **−0.462** (hands behind the body) to **+0.297** (in front). A signer's hands are always in front.
- Written to a NEW path rather than overwriting `public/skeleton/hello.json`, which stays as the committed default fixture for `skeleton-viewer.html`.

### `frontend/signer/SignLibrary.ts`
- `HELLO` now points at `/skeleton/hello_captured.json`.

### `frontend/signer/main.ts`
- ~~`SkeletonRetargeter` constructed with `{ fingerMode: 'prox' }`~~ — **superseded the same day**: `'prox'` read as stiff and lost handshape. Replaced by `'full'` + `fingerSmoothing`; see the entry above.
- **Root cause of the finger flailing:** finger depth is the capture's least reliable channel. In `how_are_you.json` the right index proximal segment swings **0.0080 → 0.0366** in view units across frames 15–23 (a 4.5× change in a physically fixed bone) exactly where the arm rises. The retargeter normalises that segment to derive a direction, so as its length collapses toward zero the direction becomes noise and the finger flails. Driving one bone per finger instead of three removes the two noisiest and keeps the handshape readable.
- Comment records the measurement and the `'full'` / `'off'` alternatives so the trade-off is tunable.

### Verification
- `npx tsc --noEmit` exit 0.
- Signer plays HELLO with the caption visible; library hint unchanged at 5 signs.
- Not yet judged: whether `'prox'` loses too much handshape detail for ISL. `'full'` restores all three bones per finger if the flailing is preferable to the loss of articulation.

---

## 2026-08-21 — new pipeline: add HOW_ARE_YOU

### `public/skeleton/how_are_you.json` (new)
- Captured from `offline/datasets/isl_greeting/how_are_you/MVI_0033.MOV` through `pipeline.app` (`mediapipe`, `space=world`): 81 frames @ 25 fps, 3.24 s, 369 KB, pipeline dialect, `meta.gloss = HOW_ARE_YOU`.
- Capture quality: **81/81 frames have both wrists tracked** — no visibility dropouts to interpolate across.

### `frontend/signer/SignLibrary.ts`
- Added one `SIGN_LIBRARY` entry: `HOW_ARE_YOU` → `/skeleton/how_are_you.json`, words `['how are you', 'how are u', 'howdy']`. Library is now 5 signs.
- `LONGEST` is derived from the library, so it widened from 2 to 3 words automatically and `how are you` matches as ONE sign rather than three unknown words.

### Verification
- `npx tsc --noEmit` exit 0.
- In-app: `[signer] HOW_ARE_YOU: 81 frames @ 25fps`; the sign completed in **3.81 s** = 3.24 s clip + ~0.57 s first fetch, then the button re-enabled.
- Caption verified live: `data-state="active"`, `opacity: 1`, text `how are you`, gloss `HOW_ARE_YOU`.
- Hint line now reads `hello · alright · good morning · good afternoon · how are you`.
- Note: playback is driven by `requestAnimationFrame`, so a **backgrounded tab throttles it** and a sign appears to hang until the tab is fronted. Normal browser behaviour, same as any rAF animation; not specific to this pipeline.

---

## 2026-08-21 — REVERT the merge; captured motion becomes its OWN app

The previous entry mixed `.vrma` clips and captured skeleton motion onto the same avatar in the same app. That is not wanted: pipeline 1 must stay exactly as it was, and captured motion belongs in a separate application. Reverted the merge and rebuilt the captured-motion path standalone.

### Reverted to original (via `git checkout`, no residue)
`backend/language/translator.py`, `backend/mapper.py`, `backend/vocabulary.json`, `data/motion_manifest.json`, `frontend/avatar/animation/AnimationController.ts`, `frontend/avatar/controller/AvatarController.ts`, `frontend/avatar/gestures/GestureRegistry.ts`, `frontend/main.ts`, `frontend/motion/DatasetLoader.ts`, `frontend/motion/MotionCatalog.ts`, `frontend/motion/MotionPlayer.ts`, `frontend/motion/MotionProcessor.ts`, `frontend/motion/loaders/MotionLoader.ts`, `frontend/sign/Sequencer.ts`, `public/skeleton/hello.json`.
- Deleted `frontend/motion/loaders/SkeletonLoader.ts` (only existed to serve the merge).
- Pipeline 1 is byte-identical to its committed state: 37 manifest entries, 26 vocabulary words, no `skeletonPath`, no skeleton mode on `AvatarController`, no `suspend()`/`resume()` on `AnimationController`.
- Verified: `POST /translate` gives `hello → [HELLO]`, `please → [PLEASE]`, `good morning → [G,O,O,D,M,O,R,N,I,N,G]` (fingerspelled, as originally). In-app `"hello please yes"` captions and plays HELLO → PLEASE → YES off the mixer.

### `frontend/signer.html` (new)
- Standalone page for the captured-motion signer. Self-contained styles (does not import pipeline 1's `style.css`), a `captured motion · no .vrma` badge, text input, caption, and a hint listing the phrases the library knows.

### `frontend/signer/SignLibrary.ts` (new)
- `SIGN_LIBRARY` (4 entries), `matchSigns()` (longest-phrase-first so `good morning` is ONE sign), `knownPhrases()`. No backend, no vocabulary.json, no manifest — this app's dictionary is this file.
- Unknown words are skipped, not fingerspelled: there are no letter clips in this pipeline.

### `frontend/signer/main.ts` (new)
- Composition root: `RenderEngine` + `VrmLoader` + `SkeletonRetargeter` only. No `AnimationMixer`, no `AvatarController`, no `.vrma`. `captureRest()` runs immediately after load while the model is still in its T-pose — nothing here applies a resting pose, so the capture is clean by construction.
- Playback advances a cursor on the engine tick at the stream's own fps and resolves a promise on the final frame, which is held (matching how a one-shot clip clamps). Streams are fetched on demand and cached.
- Fixed during verification: `data-state` was being set on `.caption__box` instead of the outer `.caption`, so the caption never became visible. Now resolved via `caption.closest('.caption')`.

### `frontend/vite.config.ts`
- Added `signer: 'signer.html'` to `build.rollupOptions.input`. Third entry alongside `main` and `skeleton-viewer`; pipeline 1's entry untouched.

### Kept from the previous work (still correct, still used)
- `frontend/avatar/animation/SkeletonRetargeter.ts` — now consumed by `VrmRenderer` and the new signer.
- `frontend/skeleton/SkeletonStream.ts` dialect aliasing — a genuine bug fix; without it offline-dialect streams render a T-pose.
- `frontend/skeleton/VrmRenderer.ts` delegation.
- `public/skeleton/{alright,good_morning,good_afternoon}.json` — the three new captured signs. `hello.json` is back to its committed offline-dialect version and works via the alias layer.

### Verification
- `npx tsc --noEmit` exit 0.
- Signer: `good morning` held its caption for exactly 3.40 s — 85 frames @ 25 fps — then resolved and reset, confirming the cursor advances at the stream's real rate. Console logs `[signer] GOOD_MORNING: 85 frames @ 25fps`.
- The two apps share no runtime state: separate pages, separate avatars, separate dictionaries.

---

## 2026-08-21 — README: run instructions for all three pipelines

### `README.md`
- Appended a "Running the pipelines" section covering the three runnable things, with a table stating plainly that **pipeline 1 and the new sign-from-video pipeline are the same application** (same servers, same URL) — what differs is whether a sign resolves to a captured skeleton stream (4) or a `.vrma` clip (36). Pipeline 2 is separate on `:8001`.
- Contents: one-time setup; `npm run dev:all` and the two-terminal equivalent; a table of what to type and which source video each captured sign came from; `curl` health/translate verification with expected output; pipeline 2 via UI and via `/api/extract`; a 6-step "adding a new sign" workflow (extract → write asset → manifest entry → vocabulary → `/admin/reload-vocab` → run tests) that documents how pipeline 2 feeds the new pipeline; the `BACKEND_PORT` override for port conflicts; and gotchas (Vite IPv6-only binding, pipeline 2 has no upload cap and never prunes `outputs/`, skeleton assets fetch on demand).
- Notes the expected `unittest` failure (digits 0–9 have no manifest entry) so a first-time reader does not read it as a regression.
- Why: three runnable surfaces across two ports with a shared config, and no single place said how to start them or how the halves connect.
- Verified: `npm run dev:all` exists in `package.json`; the documented `python3 -c` one-liner parses; `POST /admin/reload-vocab` returns `{"status":"reloaded","entries":"33"}`; the manifest example matches the real `GOOD_MORNING` entry field for field.

---

## 2026-08-21 — D3: text → captured-motion signing in the main app

Typing `hello`, `alright`, `good morning`, `good afternoon` now makes the avatar perform the motion captured from the real ISL videos, in the pipeline-1 UI. Four signs are skeleton-backed; the other 36 still play their `.vrma` clips unchanged.

### `frontend/skeleton/SkeletonStream.ts`
- Added `buildJointAliases()`, `JOINT_ALIASES`, exported `canonicalJointName()`, and `aliasJoints()`; `parseSkeletonStream()` now canonicalises joint spec names, their `parent` refs, and every frame's joint keys. Offline dialect (`leftShoulder`, `leftIndexMCP`, `leftThumbCMC/MCP/IP/TIP`, `leftHandWrist`) maps to the pipeline dialect (`lShoulder`, `lIndex1..4`, `lThumb1..3`, `lHand`); MCP→1, PIP→2, DIP→3, TIP→4; offline's thumb CMC is dropped. Streams already in the pipeline dialect are returned untouched (no allocation).
- Why: fixes the pre-existing bug logged in the entry below — offline-dialect streams left every driven bone unresolved, so the VRM rendered a permanent T-pose. Fixing it at the single read point means the viewer and the app both get it.
- Verified: `skeleton-viewer.html?renderer=vrm` at frame 30 now renders the HELLO pose instead of a T-pose.

### `frontend/avatar/controller/AvatarController.ts`
- Added `playSkeleton(frames, fps)`, `stopSkeleton()`, `isPlayingSkeleton`, private `stepSkeleton()`, a `skeleton` cursor field, and a `SkeletonRetargeter` instance. The per-frame tick now drives either skeleton playback or the mixer, never both. `relax()` also stops skeleton playback. `load()` calls `retargeter.captureRest(vrm)` **before** `applyNaturalPose()`.
- Why: one VRM, two drivers (D3). Rest must be measured in the T-pose — `applyNaturalPose()` rotates the upper arms ~80° down, and capturing after it would bake that into every rest direction.

### `frontend/avatar/animation/AnimationController.ts`
- Added `suspend()` (stops all actions, clears `current`) and `resume()` (drops cached actions so they rebuild).
- Why: the mixer and the retargeter both write the normalized humanoid bones; without stopping the actions the pose flickers between them depending on tick order.

### `frontend/avatar/gestures/GestureRegistry.ts`
- `getAll()` now filters to entries whose `assetPath` ends in `.vrma`.
- Why: skeleton-backed entries carry a `.json` `assetPath`; handing those to `VRMAGestureLoader` made GLTFLoader throw `Unsupported asset` and dropped boot registration to 37/40. Now 37/37.

### `frontend/motion/loaders/SkeletonLoader.ts` (new)
- `MotionLoader` implementation projecting a `MotionReference` to a `LoadedMotion` carrying `skeletonPath`. Streams are fetched on demand (they are ~300–400 KB each), not preloaded like `.vrma`.

### `frontend/motion/DatasetLoader.ts`
- Enabled the stubbed dataset switch: `case "skeleton": return this.skeleton;`. `manual`/untagged entries still fall through to `VRMALoader`.

### `frontend/motion/MotionCatalog.ts`, `frontend/motion/loaders/MotionLoader.ts`, `frontend/motion/MotionProcessor.ts`
- Added optional `dataset` and `skeletonPath` to `MotionReference`, `skeletonPath` to `LoadedMotion` and `ProcessedMotion`, and carried it through `process()`.

### `frontend/motion/MotionPlayer.ts`
- `play()` is now `async`: a `skeletonPath` motion is fetched via `loadSkeletonStream` + `toViewSpace`, cached in a `Map`, and handed to `avatar.playSkeleton()`; everything else takes the unchanged `playGesture` path.

### `frontend/sign/Sequencer.ts`
- `await`s `player.play()`. Captured motion holds for its own real `duration` (floored at `MIN_HOLD_SECONDS`) instead of being clamped by `MAX_HOLD_SECONDS`.
- Why: the 3 s cap exists because hand-authored `.vrma` are padded to ~10.4 s. Captured clips are their true length, so the cap would cut `good afternoon` (3.64 s) short.

### `frontend/main.ts`
- Explicit camera: `fov: 30, position: [0, 1.35, 4.6], target: [0, 1.2, 0]`; OrbitControls target matched.
- Why: the default framing put the head behind the caption and the feet under the input bar. The signer is now fully in frame and centred, with clearance above and below.

### `public/skeleton/hello.json`, `alright.json`, `good_morning.json`, `good_afternoon.json`
- Regenerated/added from `offline/datasets/isl_greeting/` (`MVI_0029`, `MVI_0037`, `MVI_0042`, `MVI_0046`) through `pipeline.app` (`mediapipe`, `space=world`) at 25 fps: 63 / 73 / 85 / 91 frames. All in the pipeline dialect with `meta.gloss` set. `hello.json` previously held an offline-dialect artifact and was replaced.

### `data/motion_manifest.json`
- `HELLO` gains `dataset: "skeleton"`, `skeletonPath: /skeleton/hello.json`, `duration: 2.52`, `motionId: video_hello_v3`; keeps its `.vrma` `assetPath` so the clip stays referenced. Added `ALRIGHT`, `GOOD_MORNING`, `GOOD_AFTERNOON` (40 entries total).

### `backend/vocabulary.json`
- Added `alright`/`okay`/`ok` → `ALRIGHT`, `good morning`/`morning` → `GOOD_MORNING`, `good afternoon`/`afternoon` → `GOOD_AFTERNOON` (33 entries). Keys may now contain spaces.

### `backend/mapper.py`
- Added `get_phrases()` returning multi-word vocabulary entries keyed by word tuple.

### `backend/language/translator.py`
- `segment()` now greedily matches the longest multi-word phrase before falling back to per-word resolution; a matched phrase becomes ONE segment captioned with the whole phrase.
- Why: the recogniser splits on whitespace, so `"good morning"` could never match a vocabulary key and was fingerspelled G-O-O-D M-O-R-N-I-N-G.
- Verified: `segment("hello good morning")` → `[('hello',['HELLO'],False), ('good morning',['GOOD_MORNING'],False)]`.

### Verification
- `npx tsc --noEmit` exit 0; `python -m unittest discover -s tests -t .` → 4 tests, 1 failure (the pre-existing digits gap, unchanged).
- In-app: all four phrases logged `playing captured motion` with frame counts matching their source videos exactly (63/73/85/91 @ 25fps); boot registration back to 37/37.
- Motion confirmed animating, not static: 8 canvas samples over 3.2 s during `good afternoon` were all pixel-distinct.

---

## 2026-08-21 — D3 skeleton playback: extract the retarget core

### `frontend/avatar/animation/SkeletonRetargeter.ts` (new)
- Extracted verbatim from `frontend/skeleton/VrmRenderer.ts`: the `Drive` interface, `sideDrives()`, the `DRIVES` table (39 entries), the `LEG_BONES`/`TORSO_BONES`/`FINGER_BONES`/`FINGER_NONPROXIMAL` sets, `captureRest()`, and the per-frame pose loop. Public surface is `captureRest(vrm)`, `applyPose(vrm, joints)`, `hasRest`; options come from a `RetargetOptions` object (`DEFAULT_RETARGET_OPTIONS` = root identity, legs off, body off, fingers full, no axis remap) instead of being read from `window.location.search`. Owns no VRM, adds no lights, touches no scene.
- Class docstring records the ordering hazard: `captureRest()` must run while the VRM is in its T-pose, because `AvatarController.applyNaturalPose()` rotates the upper arms ~80° down and that would be baked into every rest direction.
- Why: D3 — one implementation of the position→rotation math shared by `VrmRenderer` (viewer) and, next, `AvatarController` (app), so the two cannot drift. Retarget math unchanged; this is a code move.

### `frontend/skeleton/VrmRenderer.ts`
- Now delegates to `SkeletonRetargeter`. Removed the `Drive`/`sideDrives`/`DRIVES`/bone-set/`captureRest`/pose-loop code (moved, not rewritten); kept VRM ownership, its own lights, `attach`/`detach`/`dispose`, and stream/frame management. The URL debug knobs moved into a `readDebugOptions()` helper feeding `RetargetOptions`, so they stay viewer-only and cannot alter how the app signs. 335 → 144 lines.
- Why: D3 — the renderer keeps the scene-side concerns it already owned; only the math left.
- Verified: `npx tsc --noEmit` exit 0. Regression-checked against `skeleton-viewer.html?renderer=vrm` at `/skeleton/hello.json` frame 30 — render is pixel-identical before and after (both T-pose, see the pre-existing bug below), and a direct A/B in the page returned the same `rightUpperArm` quaternion for old and new code paths.

### KNOWN BUG (pre-existing, not introduced here): `public/skeleton/*.json` cannot drive the VRM
- `public/skeleton/hello.json` and `good_morning_full.json` are offline-pipeline artifacts using the offline joint dialect (`leftShoulder`, `leftElbow`, `leftWrist`, `leftHandWrist`, `leftIndexMCP`…). `DRIVES` looks up the pipeline dialect (`lShoulder`, `lElbow`, `lWrist`, `lHand`, `lIndex1`…). Only the 5 torso joints (`hips`/`spine`/`chest`/`neck`/`head`) share names, and those are undriven by default (`driveBody: false`), so **every** driven bone falls to "inherit parent frame, stay at rest" and the avatar renders a permanent T-pose.
- Proven in-page at frame 30: as-shipped `rightUpperArm` = `[0,0,0,1]` (identity/undriven); with the 8 arm joints aliased to the pipeline dialect = `[0,-0.4774,0.2931,0.8284]` (driven).
- Confirmed pre-existing by restoring the original 335-line `VrmRenderer.ts` and re-rendering the same frame: identical T-pose.
- Why it matters: this is the `source_skeleton.v1` dialect drift (two incompatible formats sharing one schema tag) surfacing as a user-visible failure. It blocks D3 — skeleton-backed signs cannot animate until the reader accepts both dialects.

---

## 2026-08-12

### `.gitignore`
- Replaced broad `offline` ignore (which hid `offline/motionpipe` + `offline/tools` code) and weak `*datasets`/`/datasets`/`/output` patterns with explicit `offline/datasets/`, `datasets/`, `**/datasets/`, `offline/output/`, `offline/.venv/` and global video/binary/image globs (`*.MOV`/`*.mov`/`*.mp4`/`*.MP4`/`*.avi`/`*.mkv`/`*.webm`/`*.m4v`/`*.jpg`/`*.jpeg`/`*.png`/`*.gif`/`*.bmp`/`*.tiff`/`*.npz`/`*.npy`) to cover the 1.5G `offline/datasets` 107 MOVs + 7.6M `offline/output` generated json/png/vrma + envs. Keeps `public/models/*.vrm` + `public/animations/*.vrma` tracked (data-driven assets). Prevents future `git add` of datasets/videos/envs without untracking existing history. Verified `git check-ignore --no-index` 139 files would be ignored, 190 kept (only `public/models/AvatarSample_C.vrm` 15M remains large & intentional).
- Deduplicated trailing ` .venv/` `venv/` `__pycache__/` `*.pyc` block (duplicate of Python section) to keep file canonical 73 lines; `git status --ignored` 21, `git ls-files --others --exclude-standard` 0.
- Why: request to ignore all image/dataset/video/env files not needed on GitHub; previous patterns did not match nested `offline/datasets/**` (verified `git check-ignore --no-index`) and `offline` was over-broad. Added global image globs per follow-up confirmation. Cleanup verifies `would-be-committed` untracked is 0.

---

## 2026-08-11 — Phase 1 clean structure: frontend / data / backend modular

### `src/` → `frontend/` (git mv) + `packages/data/` → `data/` (git mv)
- Moved `src/` (frontend code) to `frontend/` (now `frontend/api`, `frontend/avatar`, `frontend/core`, etc.), moved `src/data/motion_manifest.json` via `packages/data` to `data/motion_manifest.json:1` so `frontend` and `data` are top-level, correctly named and not duplicated. Updated `frontend/motion/MotionCatalog.ts:1` `../../data/motion_manifest.json` and `frontend/avatar/gestures/GestureRegistry.ts:1` `../../../data/motion_manifest.json`, `config.yaml:14` + `backend/config.py:17` `manifest_path`, `ARCHITECTURE.md:11` + `offline/tools/generate_vocab_manifest.py:18`, `docs/ARCHITECTURE.md` mirror.
- `frontend/index.html:11` `src="/src/main.ts"` → `"/main.ts"`, `frontend/skeleton-viewer.html:97` `"/src/viewer/..."` → `"/viewer/..."`, `vite.config.ts:67` `root: 'frontend'` + `publicDir: '../public'` + `build.outDir: '../dist'` + `server.fs.allow: ['..']` so `data/` outside root is allowed, `tsconfig.json:16` `include: ["frontend","packages","data"]`.
- Why: Phase 1 target — `frontend`, `data`, `backend` all top-level, correctly named, no dup (`src/data` was inside `frontend`).

### `infra/` + `docs/` + `apps/` + `packages/` (new)
- `infra/` already mirrors `Dockerfile*`, `docker-compose.yml`, `nginx.conf`, `config.yaml`, `requirements.txt`; `docs/` mirrors `AGENTS.md` etc.; `apps/web|api` and `packages/*` placeholders document future `apps/web` (`frontend` code) moves. Root now keeps only necessary: `README.md`, `AGENTS.md`, `config.yaml` (also in `infra`), `package.json`, `vite.config.ts`, `frontend/`, `data/`, `backend/`, `public/`, `offline/`, `infra/`, `docs/`.
- Why: main folder clean, modular for future dev; `npx tsc` 0, `npm run build` 3 chunks, `backend` health still `200`.

## 2026-08-11 — dictionary generation (A) — file-generated vocab/manifest

### `config.yaml`
- Added `backend.dictionary.path` (`backend/vocabulary.json`) + `manifest_path` (`src/data/motion_manifest.json`).
- Why: vocabulary/manifest are generated artifacts, not hardcode — offline pipeline writes them.

### `backend/config.py`
- Added `dictionary` to `_DEFAULTS`, `DICTIONARY_PATH` env override, `get_dictionary_path()`/`get_manifest_path()`, and validation.
- Why: make vocab path config-driven, single source infra/config.yaml.

### `backend/mapper.py`
- `_vocabulary_path()` now reads `get_dictionary_path()` (repo-root or backend relative), `_load_vocabulary(path)` takes path, `reload_vocabulary()` hot-reloads (atomic swap, returns count). `_VOCABULARY` now documented as generated artifact.
- Why: every ISL can work after `offline/tools/generate_vocab_manifest.py` → merge → `POST /admin/reload-vocab` (no restart).

### `backend/app.py`
- Added `POST /admin/reload-vocab` (calls `reload_vocabulary()`, logs count) for hot-reload after offline pipeline.
- Why: no restart needed when dictionary grows from 27 → 1000.

### `offline/tools/generate_vocab_manifest.py` (new)
- Scans `public/animations/*.vrma` vs `src/data/motion_manifest.json` (orphans/missing), prints merge-ready fragments for new word/gloss/vrma (`--scan`, `--new-word namaste --gloss NAMASTE --vrma ...`), notes `reload-vocab`.
- Why: A — file-generated vocab/manifest, minimal code, no DB yet.

### `.env.example`
- Added `DICTIONARY_PATH`, `BACKEND_HOST`, `LOG_LEVEL` overrides.
- Why: env wins over yaml for deploy.

## 2026-08-11 — Phase 5 integration + evaluation

### `offline/motion_analysis/recognize.py` · `evaluation.py` (new)
- `recognize.py`: CLI `python -m offline.motion_analysis.recognize --query query.npz --database ...` (EEMGM, chunk 10, threshold 0.2). `evaluation.py`: `motion_quality()`, `graph_similarities()` (mean/median/std body/left/right/fingers), `evaluate()` for baselines A-D, perf (speedup/reduction), motion frames (retention), signer variation note. Synthetic N=30 → metrics.json/summary.csv/comparison_report.md at `offline/output/evaluation/` (same 0.289 < diff 0.298 PASS, 3600→600 comps 0.83 reduction 2.39 speedup, retention 100% vs paper 25%).
- Why: Phase 5 — offline research stays callable, production VRM untouched, measure don't claim.

## 2026-08-11 — Phase 4 graph matching + EEMGM

### `offline/motion_analysis/graph_matching.py` · `eemgm.py` (new)
- `graph_matching.py`: `compare_frames()` (d_v/d_e, vertex/edge/combined + body/left/right/finger scores), `compare_sequences()` M_V/M_E/combined, `normalize_modes()` raw/pelvis/scale. `eemgm.py`: `SignDatabase`/`SignEntry`, 10-frame chunks, threshold 0.2 + consecutive 5, early exit, final validation, `compare_full_vs_eemgm()` (speedup/reduction). Synthetic N=20 same 0.0 vs diff 0.28, seq same 0.354 < diff 0.377, EEMGM predicted hello early, 200 vs 800 comps (0.75 reduction, 1.34 speedup).
- Why: Phase 4 — paper Eq 9 + EEMGM offline, synthetic validated; real NPZ pending.

## 2026-08-11 — Phase 3 3D graph + intra motion

### `offline/motion_analysis/` (new)
- `topology.py` (55 SMPL-X names + 52 edges), `graph.py` (SkeletonGraph/Sequence/MotionFrameResult, from_npz, extract_motion_frames with paper_mode/percentile/absolute), `features.py` (pelvis_centered/scale/shoulder_width, vertex/edge motion), `__init__.py`. Synthetic N=10 J=55 E=52 validated: edges valid/no dups/finite/round-trip, pelvis_centered, paper_mode thresholds (max*0.2).
- Why: Phase 3 — paper G_t=(V_t,E_t) using actual SMPL-X, not 57 Vicon.

## 2026-08-11 — Phase 2 SMPLest-X exporter verified, inference pending

### `offline/colab/export_smplestx_npz.py` (verified, no code change)
- Verified via AST grep: collects all 9 tensors (`smplx_root_pose`…`smplx_joint_cam`), POSE_DIM 165 (45*2 hands), FPS 25, single-person abort (>1 raises). No invented outputs.
- Why: Phase 2 step 1 — exporter must mirror SMPLest-X official API.

### `offline/output/smplx/README.md` (new)
- Documents empty until Colab T4 + `smplest_x_h` checkpoint produces `isl_hello_MVI_0029.npz`; gives exact export + validate commands.
- Why: Phase 2 output contract.

### `offline/tools/validate_npz.py` (new)
- Checks (N,165), (N,3), (N,J,3) J≥55, finite, FPS — fails fast for Phase 2 step 3.
- Why: NPZ validation tool ready before real inference.

### `offline/README.md`
- Updated Status to 2026-08-11: foundation+MediaPipe DONE (vrma/hello_isl etc), SMPLest-X exporter VERIFIED, real inference PENDING Colab.
- Why: Phase 1 doc sync was false (claimed NotImplementedError); now accurate.

### `backend/implementations/Phase2.txt`
- Marked exporter DONE, inference/visual PENDING Colab, added tool paths and 165-dim detail.
- Why: Phase 2 now honest about what is local vs Colab-only.

## 2026-08-11 — Phase 1 repo structure & dead-code cleanup

### `backend/mapper.py`
- Added `DeprecationWarning` to `map_gloss()` (was silent passthrough). Now warns `use map_recognition()`.
- Why: Phase 1 dead-code audit — keep deprecated, don't delete file blindly.

### `public/animations/Please.vrma` · `hello_sign.vrma` · `isl_greeting__hello__MVI_0029.vrma` (deleted)
- Verified via grep: no `motion_manifest.json` entry (HELLO uses `hello_isl.vrma`, PLEASE uses `please_sign.vrma`), no code import. Deleted 3 orphans.
- Why: Phase 1 orphan cleanup.

### `public/models/avatar.vrm` (deleted)
- 14 MB dup of `AvatarSample_C.vrm` (15 MB, `APP_CONFIG.avatar.modelPath`). No reference after config. Deleted.
- Why: dedup.

### `infra/` · `docs/` · `apps/` · `packages/` (new dirs)
- Created `infra/` (mirrors Dockerfile, docker-compose, nginx, config.yaml, requirements), `docs/` (mirrors AGENTS, ARCHITECTURE, CHANGELOG, PIPELINE), `apps/web|api/README`, `packages/core|avatar|skeleton/README` as future structure placeholders. Root keeps canonical files for `run.sh`/`vite`/`backend/config.py` (now checks `config.yaml` or `infra/config.yaml`).
- Why: Phase 1 clean layout for future dev without breaking `npx tsc`/`npm run build`.

### `backend/config.py` · `vite.config.ts`
- `backend/config.py` now checks `config.yaml` and `infra/config.yaml`; `vite.config.ts` `configPath()` checks both.
- Why: support future `infra/`-only layout.

## 2026-08-11 — compress implementations phases, add structure cleanup

### `backend/implementations/Phase*.txt`
- Compressed 8 verbose phases (800+ lines) to 5 priority phases (123 lines): Phase1 now Repo Structure & Hygiene (new — proposes apps/web, apps/api, packages/*, infra/, docs/, fixes scattered root), Phase2 SMPLest-X Capture, Phase3 3D Graph + Intra, Phase4 Matching + EEMGM, Phase5 Integration + Evaluation. Removed done: AGENTS/README/PIPELINE sync, HANDOVER deletion, vocab `I`→`i`, frontend/venv removal; marked pending: orphan `Please.vrma`/`hello_sign.vrma`/`avatar.vrm` dup, mapper `map_gloss` deprecation, offline/README NotImplementedError. Fixed order: merged Phase3+4, Phase5+6, Phase7+8; deleted Phases 6-8.
- Why: remove done/false, keep only diff/priority, make repo clean for future dev.

## 2026-08-11 — lift avatar above input bar

### `src/avatar/controller/AvatarController.ts`
- Set `vrm.scene.position.y = 0.2` after load so feet clear the bottom `SignControls` bar overlay.
- Why: legs were visually overlapping the input bar.

## 2026-08-11 — README precise (normal + docker)

### `README.md`
- Made precise: Normal → `http://localhost:5173`, Docker → `http://localhost` (nginx `80`, or `http://localhost:3000` with `FRONTEND_PORT`), removed `docker build -t` single-image section and duplicate `What runs where` table, removed stale `HANDOVER.md` line. Added **Restart after file changes** (`docker compose up --build` / `restart backend` for mounted `config.yaml`). Kept `Other commands` minimal.
- Why: requested Docker-only via compose, correct frontend access, and rebuild instruction.

## 2026-08-11 — README docker + normal run

### `README.md`
- Rewrote `## Running it` with two top-level sections: **Normal (local dev)** (`./run.sh`, `npm run dev:all`, two-terminals from repo root with `backend.app:app` + Vite proxy note) and **Docker (production)** (`docker compose up --build`, single-image builds, `FRONTEND_PORT` override). Added services table for nginx vs Vite, health `/health`/`/ready`, `BACKEND_HOST=0.0.0.0` note. Added docker commands to `## Other commands` and Docker-aware `## Troubleshooting` (health curl, `compose ps`, `compose down`, `0`–`9` digits caption-only).
- Why: start must show both normal and Docker running correctly.

## 2026-08-11 — P3 docker-ready & config hardcoding removal

### `config.yaml`
- Added `backend.rate_limit` (30/min, 60s), `backend.log_level`, `backend.max_body_bytes` (8192), `frontend.timeout_ms` (8000), `backend.host` comment for Docker (`0.0.0.0`). All tunables now in one file.
- Why: P3-4/P3-5 — timeout/rate-limit/log/host were untunable hardcodeds.

### `backend/config.py`
- Added `rate_limit`/`log_level`/`max_body_bytes` to `_DEFAULTS` and `frontend.validation`/`avatar.word_priority` fallbacks; added `BACKEND_HOST`/`LOG_LEVEL`/`VITE_API_URL` env overrides; replaced silent `except: pass` with warning log + `_validate_and_normalize()` (port range, CORS URL scheme, trailing-slash strip). Added `get_rate_limit()`/`get_log_level()`.
- Why: P3-5 config validation — malformed yaml no longer silent.

### `backend/app.py`
- Wired `get_rate_limit()`/`get_log_level()`/`_cfg["max_body_bytes"]`; added `guard_body_size` middleware (413), made rate limit config-driven, log level from config. Host still 0.0.0.0-ready via `BACKEND_HOST`.
- Why: P3-4/P3-5 production observability.

### `vite.config.ts` · `run.sh` · `scripts/dev.mjs`
- All now read `backend.host` from `config.yaml` (env `BACKEND_HOST` wins) for proxy `target`, `net.connect` host, `uvicorn --host`, health `curl`. `BACKEND_HOST=0.0.0.0` makes Docker work.
- Why: P3-1 host was `127.0.0.1` everywhere — broke containers.

### `src/config/appConfig.ts` (new) · `vite.config.ts:define`
- Added Vite `define: { __APP_CONFIG__: JSON.stringify(frontendConfigFromYaml()) }` parsing `config.yaml` (timeout, validation, animation 7 values, avatar model/concurrency/wordPriority, speeds). `src/config/appConfig.ts` exposes `APP_CONFIG` with fallback defaults. All frontend hardcodeds now read from it: `src/api/translate.ts:9` timeout, `src/ui/SignControls.ts:31` maxLength, `src/ui/PlaybackSpeedControl.ts:17` speeds, `src/sign/Sequencer.ts:15` + `src/avatar/animation/AnimationController.ts:22` 7 animation timings, `src/avatar/controller/AvatarController.ts:121` concurrency/wordPriority, `src/main.ts:123` model path.
- Why: P3-2/P3-3 — 7 files duplicated `config.yaml` values and drifted.

### `Dockerfile` · `Dockerfile.frontend` · `docker-compose.yml` · `nginx.conf` · `.dockerignore` (new)
- Multi-stage backend (python 3.13-slim, `HEALTHCHECK curl /ready`, `BACKEND_HOST=0.0.0.0`) and frontend (node 20 build → nginx, `HEALTHCHECK wget`, `proxy_pass /api/` to backend with `X-Forwarded-*`). `docker-compose.yml` orchestrates both with `service_healthy` dependency, port envs, volume for `config.yaml`. `nginx.conf` handles SPA `try_files` + gzip. `run.sh` now health-waits 20s before opening browser.
- Why: P3-6 docker-ready production — `docker compose up --build` works, graceful SIGTERM via uvicorn/nginx.

## 2026-08-11 — run.sh / launcher config.yaml wiring

### `run.sh`
- Now reads `config.yaml` (`backend.port` / `frontend.dev_port`) with `FRONTEND_ORIGIN`/`BACKEND_PORT`/`FRONTEND_PORT` env overrides; falls back to 8000/5173 if yaml or `pyyaml` missing. Installs from universal `requirements.txt` (with `pyyaml`/`httpx`) and re-installs on existing venv. Waits for `GET /health` (curl loop, 80×0.25s) before opening browser, not just `port_busy`. Uses `127.0.0.1` host explicitly for uvicorn; logs config source.
- Why: single source `config.yaml` — ports/CORS no longer hardcoded in launcher.

### `vite.config.ts`
- Added `backendPortFromConfig()` reading `config.yaml` (regex, env wins) and `target: 127.0.0.1:${BACKEND_PORT}` for `/api` proxy.
- Why: Vite proxy must follow `config.yaml`.

### `scripts/dev.mjs`
- Added `portFromConfig()` + env override for both ports; updated pip hint to `requirements.txt`.
- Why: `npm run dev:all` parity with `run.sh`.

## 2026-08-11 — remove stale files

### `HANDOVER.md` (deleted)
- Removed 359-line stale handover doc flagged in `AGENTS.md:2.5` as untrusted/older state; `AGENTS.md` is the authoritative guide.
- Why: unnecessary .md — requested cleanup.

### `frontend/` + `frontend/venv/` (deleted)
- Removed `frontend/venv/` (12 MB stray empty virtualenv, only content of `frontend/`). Repo venv lives at `.venv` at root per `AGENTS.md`.
- Why: unnecessary stray, `.gitignore` already excludes `.venv`/`venv`.

## 2026-08-11 — P2 hardening (config, error boundaries, observability, bundle)

### `config.yaml` (new) · `requirements.txt` (new) · `backend/config.py` (new)
- Universal `config.yaml` (backend host/port/cors/validation, frontend dev_port/api_url, animation fade/hold/fingerspell/speeds, avatar model/concurrency/priority) with env overrides (`FRONTEND_ORIGIN`, `BACKEND_PORT`). `requirements.txt` at root (fastapi, uvicorn, pydantic, pyyaml, httpx) and `backend/requirements.txt` now `-r ../requirements.txt`.
- `backend/config.py` `load_config()` deep-merges yaml over defaults, caches, handles missing/malformed yaml; `get_cors_origins()` / `get_validation_limits()` wired into `backend/app.py:16` and `backend/schemas.py:5`.
- `.env.example` header now references `config.yaml` as source of truth.
- Why: P2-6 universal config — eliminates hardcoding, single tunable file.

### `src/core/RenderEngine.ts`
- Added `isWebGLAvailable()` check, `showFallback()` alert, try/catch around `ResizeObserver`/`WebGLRenderer`/`dispose`, and `webglcontextlost`/`restored` listeners (pause/resume clock).
- Why: P2-1 frontend error boundaries — context loss no longer stalls.

### `backend/app.py`
- Added `X-Request-ID` middleware (uuid + timing log), per-IP rate limit (30/min on `/translate` → 429), and exception handlers for `RequestValidationError` (422) and generic `Exception` (500) with `logging` structured output.
- Why: P2-2 observability — request tracing and backpressure.

### `backend/mapper.py` · `backend/language/translator.py`
- Wrapped `vocabulary.json`/`alphabet.json` loads in `_load_*()` with validation (lowercase keys, string values) and warning fallback to `{}`.
- Why: P2-3 import-time crash — malformed JSON no longer kills process; `/ready` probe surfaces it as 503.

### `vite.config.ts`
- Added `chunkSizeWarningLimit:600` and `manualChunks(id)` splitting `three` and `three-vrm` — build now yields `three` 634k + `three-vrm` 169k + smaller `main`; warnings gone.
- Why: P2-5 bundle code-split, modular.

### `backend/language/recognizer.py`
- Added `DeprecationWarning` to `recognize()`/`last()` directing to `split()`.
- Why: P2-7 concurrency — stateful path deprecated, stateless `split()` is canonical.

### `tasks.md`
- Marked P2-1, P2-2, P2-3, P2-5, P2-6, P2-7 as done; P2-4 skipped per request.

## 2026-08-11 — P1-4 & P1-5 fixes (dead-tail leave-as-is, docs drift)

### `tasks.md`
- Fixed P1-1 checkbox (`- []` → `- [x]`) and marked P1-4 (dead-tail clamp leave-as-is, MAX=3/MIN=1.5 until `.vrma` re-export) and P1-5 (docs drift) as done.

### `backend/PIPELINE.md`
- Fixed fingerspelling diagrams: `LETTER_H` → `H`, `regex \w` → `[a-z0-9]`, `LETTER_*` examples → bare `A`/`B`, `DIGIT_1` → `1`, Added P1-1 note on digits caption-only. Updated known gap from 36 missing clips to 10 digit clips (A-Z now have assets).
- Why: P1-5 docs still described pre-2026-08-04 `LETTER_*`/`DIGIT_*` scheme; code uses bare ids since `alphabet.json:2` change.

## 2026-08-11 — P1-2 & P1-3 fixes (vocab casing, bounded gesture load)

### `backend/vocabulary.json`
- Changed `"I": "ME"` → `"i": "ME"` so `TextNormalizer` (lowercases) matches. Verified `segment("I")` → `ME`.
- Why: P1-2 — uppercase key was dead.

### `src/avatar/controller/AvatarController.ts`
- Replaced `Promise.all` batch with concurrency-limited `Promise.allSettled` (limit 6) + word-sign priority sort (`HELLO`…`BYE` first), per-batch `registered` count and `caption-only fallback` warn.
- Why: P1-3 — avoid flooding network, prioritize core vocab, resilient to single bad `.vrma`.

### `backend/language/translator.py`
- Tightened `_CHARACTER` from `\w` to `[a-z0-9]` and documented digit caption-only leave-as-is.
- Why: P1-1 follow-up — `_` no longer a bogus token; digits intentionally hold caption only until assets exist.

### `tasks.md`
- Marked P1-1 (leave-as-is), P1-2, P1-3 as done.

## 2026-08-11 — natural resting pose instead of T-pose

### `src/avatar/controller/AvatarController.ts`
- Added `import * as THREE`, `applyNaturalPose(vrm)` that sets normalized humanoid pose (upper arms ~65° down from T-pose, slight elbow bend, hands relaxed) via `vrm.humanoid.setNormalizedPose` + `update()`, called after `loadGestures` before tick subscription.
- Why: avatar no longer holds T-pose when idle or after `relax()`; natural pose is the fallback whenever no gesture clip is active.

## 2026-08-11 — rotate indicator at top-right, remove bottom status

### `src/ui/ActivityIndicator.ts` (new)
- Top-right rotating spinner (`activity` + `activity__spinner`) shown while avatar loading / translating / signing, hidden otherwise; colour-matched to `var(--red)` on `var(--hairline)` track, 0.7s linear `activity-spin`.
- Why: replace centre-bottom `Ready`/`Done` text with conventional busy indicator.

### `src/style.css`
- Hid `.bar__message` (`display: none`) and added `.activity` / `.activity__spinner` + `@keyframes activity-spin`; added reduced-motion slowdown.
- Why: centre status removed per request; spinner must respect `prefers-reduced-motion`.

### `src/main.ts`
- Created `ActivityIndicator`; `onSign` now drives `activity.show()`/`hide()` instead of `showMessage('Translating…'/'Signing…'/'Done'/'Ready')`; boot shows spinner until avatar ready then hides it. Removed ready/done/nothing-to-sign/timeout error text toasts.
- Why: composition root owns busy state; caption remains the only text feedback.

## 2026-08-11 — playback speed control

### `src/ui/PlaybackSpeedControl.ts` (new)
- Bottom-right `1x` button that cycles `1x → 2x → 3x → 4x → 5x → 1x`, calling `onChange` with the selected multiplier.
- Why: user-requested global animation speed.

### `src/avatar/animation/AnimationController.ts`
- Added `playbackRate` + `setPlaybackRate(rate)` (sets `mixer.timeScale`) and `playbackRateValue`; `attach` now applies stored rate.
- Why: mixer is the single place that scales clip playback; VRM update follows it.

### `src/avatar/controller/AvatarController.ts`
- Added `setPlaybackRate(rate)` delegating to `AnimationController`.
- Why: keep `AnimationController` private — composition root talks only to the `AvatarController` facade.

### `src/sign/Sequencer.ts`
- Added `playbackRate` + `setPlaybackRate`/`playbackRateValue`; `playGesture` divides missing-motion and hold delays by `playbackRate`.
- Why: hold timing must stay in sync with the sped-up mixer, otherwise caption and avatar drift.

### `src/style.css`
- Added `.speed-control` — fixed bottom-right pill matching input bar styling.
- Why: visible, accessible speed control without competing with the avatar.

### `src/main.ts`
- Wires `PlaybackSpeedControl` to `avatar.setPlaybackRate` + `sequencer.setPlaybackRate`.
- Why: composition root owns the single speed state and fans it to both layers.

## 2026-08-11 — fix P0 doc/type drift

### `backend/app.py`
- Moved `JSONResponse` import to top and added `response_model=None` to `GET /ready`; changed return type to `dict[str,str] | JSONResponse`. Fixes `FastAPIError: Invalid args for response field` when ready returns 503.
- Why: Pydantic cannot validate `Union[dict, Response]` as response_model; disabling it for the probe endpoint is the documented fix.

### `AGENTS.md`
- Updated `src/api/translate.ts` line from hard-coded `http://127.0.0.1:8000/translate` to `fetch POST /api/translate (VITE_API_URL or Vite proxy)`.
- Rewrote `backend/` layout block to reflect real files (`app.py` with `/health`+`/ready`+`FRONTEND_ORIGIN`, `schemas.py` with 500-char validation, `mapper.py`/`language/` actual modules) and added `__init__.py`.
- Updated `§2.4 Runtime contract` from hard-coded `127.0.0.1:8000` + `["UNKNOWN"]` to `VITE_API_URL`/`/api` + `422` on blank/oversize + `GET /health`+`/ready` + `FRONTEND_ORIGIN` origins.
- Why: verification flagged doc drift — code had been fixed but AGENTS.md still described the old P0-broken state.

## 2026-08-11 — P0 reliability fixes (hard-coded URL, timeout, CORS, health, validation, package layout)

### `.env.example` (new)
- Documents `VITE_API_URL` and `FRONTEND_ORIGIN` so both servers are configurable via env instead of hard-coded.
- Why: production needs a different origin than `127.0.0.1:8000`; Vite requires `VITE_` prefix to expose vars to the client.

### `vite.config.ts`
- Added `server.proxy` for `/api` → `http://127.0.0.1:8000` (rewrites `/api/translate` → `/translate`).
- Why: lets the frontend use a relative URL when `VITE_API_URL` is unset, so dev and prod share the same code path and `127.0.0.1:8000` is no longer baked into the bundle.

### `src/api/translate.ts`
- Replaced hard-coded `http://127.0.0.1:8000/translate` with `VITE_API_URL` / `/api/translate` fallback.
- Added `TranslateOptions` (`signal`, `timeoutMs`), `AbortController` + 8s timeout, propagation of caller signal, and richer error detail (422 body).
- Why: P0-1 deploy break + P0-2 hanging fetch; timeout surfaces as `TimeoutError` and caller abort is respected.

### `src/main.ts`
- Added `pendingTranslate` `AbortController`, abort-on-resubmit, and distinct handlers for `AbortError`/`TimeoutError`/422 vs generic network error.
- Why: re-submit no longer races the previous translate; user gets actionable messages (`too long` vs `backend not running`).

### `backend/app.py`
- Restricted `CORSMiddleware` to `FRONTEND_ORIGIN` env (comma-separated, default `localhost:5173`+`127.0.0.1:5173`) and `["GET","POST","OPTIONS"]` + `Content-Type`/`Authorization`.
- Added `GET /health` (liveness) and `GET /ready` (probe `segment("hello")`, 503 on failure) for orchestrators and `run.sh`.
- Made imports dual-compatible (`language.*` when `cwd==backend`, `backend.language.*` when `cwd==repo`/`backend.app`).
- Why: P0-3 `*` was insecure, P0-4 no probe, and `uvicorn` failed when run from repo root.

### `backend/schemas.py`
- Added `Field(min_length=1,max_length=500)` and `field_validator` stripping/empty check on `TranslateRequest.text`.
- Why: unbounded input was a DoS vector; empty/whitespace now 422s instead of returning `[]` silently.

### `src/ui/SignControls.ts`
- Set `input.maxLength=500` and `maxlength` attribute.
- Why: frontend enforces the same 500-char limit before the request leaves the browser.

### `backend/__init__.py` · `backend/language/__init__.py` (new)
- Package markers so `backend`/`backend.language` are proper packages, not namespace packages.
- Why: `PIPELINE.md:8` fragility — packaged runs and `python -m backend.app` now resolve.

### `backend/mapper.py` · `backend/language/translator.py`
- Wrapped top-level `from mapper`/`from language.recognizer` imports with `try/except ImportError` fallback to `backend.*`.
- Why: dual cwd compatibility for P0-6.

## 2026-08-11 — task list for reliable production app

### `tasks.md` (new)
- Created `P0`/`P1`/`P2` task list from repo analysis (hard-coded API URL, no fetch timeout, CORS `*`, no health check, no input validation, broken Python package layout, digit/casing data bugs, unbounded gesture load, clip duration drift, error boundaries, observability, tests/CI, bundle hygiene).
- Why: make the reliability gaps explicit and ordered so P0 can be worked through sequentially with `tsc && vite build` gates.

## 2026-08-11 — skeleton stream viewer (decouple motion data from the avatar)

Refocus: the low-level VRM retargeting (`target_rotations.py`) is the fragile link, so the fix is not to repair it but to stop it being load-bearing. The canonical `source_skeleton.v1` stream becomes the interchange format; a neon-armature viewer proves captured motion with zero dependence on the broken VRM path, and renderers become hot-swappable consumers behind one interface.

### `src/core/RenderEngine.ts` · `src/core/Clock.ts` (moved from `src/avatar/core/`)
- Moved the shared render infra out of the avatar module into a top-level, VRM-free `core/` module, so the skeleton viewer can reuse it without importing avatar internals.
- Why: the neon viewer must have no VRM in its module graph; sharing one render engine keeps renderers consistent and avoids a second render loop.

### `src/avatar/controller/AvatarController.ts` · `src/main.ts`
- Updated the `RenderEngine` import path (`../../core/…` / `./core/…`). No behavior change.

### `src/skeleton/SkeletonStream.ts` (new)
- Canonical stream contract: named joints + parent→child hierarchy + per-frame `[x,y,z,confidence]`, three.js-free.
- `parseSkeletonStream()` validates `source_skeleton.v1`; `loadSkeletonStream()` fetches + validates; `toViewSpace()` converts to Y-up, per-frame root-centered at hips, unit-scaled (mean hip→head = 1) — the ONE place coordinate conventions are resolved, so no renderer re-derives them.
- Handles missing joints (`null`) per frame; the MediaPipe stream drops the right hand in 6 frames.

### `src/skeleton/SkeletonRenderer.ts` (new)
- `SkeletonRenderer` interface (setStream / setFrame / attach / detach / dispose) — the hot-swap seam. `SkeletonPlayer` owns playback timing (fps-scaled, loop/clamp) and pushes frame numbers, so swapping renderers resumes at the same frame.

### `src/skeleton/NeonLineRenderer.ts` (new)
- Reference `SkeletonRenderer`: draws the armature as additive-glow `LineSegments` (bright core + extended halo) over the hierarchy edges, with joint `Points`. Positions only — no rotations, no `@pixiv/three-vrm`.

### `skeleton-viewer.html` · `src/viewer/skeleton-viewer.ts` (new)
- Standalone debug page at `/skeleton-viewer.html`: loads a stream, plays it back as neon lines, with orbit/zoom, play/pause/restart, scrub, speed, and loop controls. Loads `/skeleton/hello.json` by default, `?src=` overrides.

### `vite.config.ts` (new)
- Multi-page build input so `npm run build` emits both `index.html` and `skeleton-viewer.html` (previously the viewer only worked in dev).

### `public/skeleton/hello.json` (new)
- Copy of the MediaPipe-derived `offline/output/source_skeleton/isl_greeting__hello__MVI_0029.json` (63 frames @ 25 fps, 59 joints) for the viewer to play.

### `AGENTS.md`
- Layout updated for the `core/` move, the new `skeleton/` + `viewer/` modules, `skeleton-viewer.html`, `vite.config.ts`, and `public/skeleton/`; added contract 2.3.7 (SkeletonStream is the universal motion format, `toViewSpace` owns coordinate conventions once); §4 documents the viewer URL.

### `dist/` (regenerated, not hand-edited)
- `npm run build` rerun so both pages ship. The viewer chunk is VRM-free (~7 kB + shared three.js).

### Not done (next steps, deliberately out of scope)
- No VRM renderer behind the `SkeletonRenderer` interface yet — that is the follow-up once the neon path proves the capture is good.
- SMPL-X streams: `smplx_adapter` output already feeds `source_skeleton.v1`, so a Colab-derived stream can be dropped into `public/skeleton/` and viewed as-is.
- `target_rotations.py` (the fragile position→rotation→VRM retarget) left untouched.

---

## 2026-08-06 — add SWAG word sign

`swag` was in `vocabulary.json` and `motion_manifest.json` but missing from `GestureManifest.ts`, so its clip was never registered: the backend emitted the id but `AnimationController` had no clip for it, and the avatar held without moving. The id was also lowercase, against the all-UPPERCASE convention.

### `src/avatar/gestures/GestureManifest.ts`
- Registered `{ id: 'SWAG', url: '/animations/swag_sign.vrma' }`. 37/37 clips now register (verified in-browser).

### `src/motion/motion_manifest.json`
- Renamed key `swag` → `SWAG` to match the id convention.

### `backend/vocabulary.json`
- Normalized value `"swag": "swag"` → `"swag": "SWAG"`. **Needs a backend restart** — config is read once at import.

---

## 2026-08-06 — register letters T–Z (full A–Z alphabet)

T–Z were already in `motion_manifest.json` with their `.vrma` assets present, but weren't in `GestureManifest.ts`, so they caption-only'd (a word containing them skipped those letters).

### `src/avatar/gestures/GestureManifest.ts`
- Registered `T`–`Z` → `/animations/{X}_sign.vrma`. The full A–Z alphabet now animates, so any unknown word fingerspells completely. 36/36 clips register.

---

## 2026-08-06 — single-letter 500 fix + fingerspelling speed

**Issue 1 — single letters crashed the backend (500).** `vocabulary.json` had letter rows as arrays (`"a": ["A"]`) inside a word→gesture-id *string* map. A letter a–s resolved to a list, which `translator.resolve_vocabulary` wrapped into a nested list `[["A"]]`; `app.py`'s Pydantic `list[str]` response model then 500'd. (t–z worked — not in the vocab, so they fell through to fingerspelling.)
- `backend/vocabulary.json` — removed the 19 letter rows. Single letters now follow the same path as any unmapped word (recognise → fingerspell via `alphabet.json`). `A`, `HELLO A`, `PLEASE B` work; no special-casing.

**Issue 2 — fingerspelling too slow.** The Sequencer held every gesture for its clip's real length (~1s per letter).
- `src/sign/Sequencer.ts` — added `FINGERSPELL = { holdSeconds: 0.45, fadeSeconds: 0.08 }`; `playGesture` now branches on the segment's `spelled` flag. Word signs keep clip-length timing; letters use the short fixed hold + tight fade.
- `src/avatar/animation/AnimationController.ts`, `controller/AvatarController.ts`, `src/motion/MotionPlayer.ts` — `play`/`playGesture` gained an optional `fadeSeconds` (defaults to the standard fade), so letters get a shorter crossfade. Additive; word behavior unchanged.

---

## 2026-08-06 — fix letter R

`R` never played: its asset (`R_sign.vrma`) now exists and it's in `motion_manifest.json`, but it was never in `GestureManifest.ts` (skipped in the earlier batch when the file was missing), so the clip was never loaded/registered.

### `src/avatar/gestures/GestureManifest.ts`
- Registered `{ id: 'R', url: '/animations/R_sign.vrma' }`. The chain is now complete (asset + `alphabet.json` `r`→`R` + `motion_manifest` + registration). A frontend hard-reload picks it up — the backend already emits `R`.

---

## 2026-08-04 — integrate FREAKY word sign

Wired up the newly-added `freaky.vrma` (305 KB) across all three layers.

### `src/motion/motion_manifest.json`
- Fixed invalid JSON — the `"S"` entry was missing its trailing comma before `"freaky"`, so the whole manifest failed to parse (500 on import; the app wouldn't load).
- Renamed the new key `"freaky"` → `"FREAKY"` to match the uppercase gesture-id convention.

### `src/avatar/gestures/GestureManifest.ts`
- Registered `{ id: 'FREAKY', url: '/animations/freaky.vrma' }` so the clip loads.

### `backend/vocabulary.json`
- Added `"freaky": "FREAKY"` so the word maps to the sign instead of being fingerspelled.

Flagged (not fixed here): `vocabulary.json`'s letter entries are arrays (`"a": ["A"]`) in a string→string map — a single-letter word would emit a nested list downstream. Also `"I": "ME"` won't match (the recogniser lowercases first).

---

## 2026-08-04 — fingerspelling now animates (letters registered + id scheme aligned)

The newly-added letter VRMAs never played. Three layers disagreed on the letter id: the backend emitted `LETTER_*` (`alphabet.json`), while the assets and `motion_manifest.json` use bare ids (`A`, `A_sign.vrma`), and **no letters were in `GestureManifest.ts`** — so their clips were never registered and `MotionCatalog` never resolved them. Aligned everything to the bare-letter scheme the assets already use.

### `backend/language/alphabet.json`
- Changed every entry from `LETTER_*` / `DIGIT_*` to the bare id (`"a": "A"`, `"0": "0"`). This is the id that flows through the whole pipeline, so backend, `motion_manifest.json`, and `GestureManifest.ts` now agree. (Supersedes the `LETTER_*` scheme noted in the 2026-08-04 fingerspelling entry below; `PIPELINE.md`/`AGENTS.md` references to `LETTER_*` are now stale.)

### `src/avatar/gestures/GestureManifest.ts`
- Registered 18 fingerspelling clips: `A`–`Q` (`/animations/{X}_sign.vrma`) and `S` (`/animations/s_sign.vrma`, the actual lowercase filename). A clip is only loaded if it has a `GestureManifest` entry, so these were the missing link.

### Known gaps (skipped gracefully, not fatal)
- `R` has no `.vrma` asset — words with "r" spell the other letters and skip R with a console warning. Drop `R_sign.vrma` into `public/animations/` to complete it.
- `T`–`Z` and digits have no assets/manifest entries → caption-only.

---

## 2026-08-04 — gesture blending (fixes snappy playback)

Diagnosed via Blender MCP: the rig has a complete VRM hand (16 bones/side) and the source clips are BEZIER-interpolated with all 30 finger bones animated. The snappiness was entirely runtime.

### `src/avatar/animation/AnimationController.ts`
- Set `clampWhenFinished = true` on every action. Previously a finished `LoopOnce` action stopped being applied and all bones snapped back to bind pose at the end of every sign — the largest single cause of snappy playback.
- `play()` now cross-fades: the outgoing action fades 1→0 while the incoming fades 0→1 over `GESTURE_FADE_SECONDS`, instead of `reset().play()` cutting straight to full weight.
- Added `current` to track the action holding the body between calls.
- Added `relax()` — eases out of the last gesture back to rest at 2.5× the normal fade.
- Added `getDuration(id)` returning the clip's real length.
- Exported `GESTURE_FADE_SECONDS` (0.22s) so playback timing can overlap it.

### `src/avatar/controller/AvatarController.ts` · `src/avatar/index.ts`
- Facade gains `getGestureDuration()` and `relax()`; barrel re-exports `GESTURE_FADE_SECONDS`.

### `src/motion/MotionPlayer.ts`
- Added `getDuration()` and `relax()` delegating to the avatar.

### `src/sign/Sequencer.ts`
- Times on the clip's real duration, falling back to the manifest only when unknown. The manifest claimed 2.1s for HELLO against a 1.67s clip, leaving the avatar parked in bind pose between signs.
- Holds for `duration − GESTURE_FADE_SECONDS` so the next sign blends in as the current one lands, floored by `MIN_HOLD_SECONDS` (0.18s).
- Replaced `GAP_SECONDS` with that overlap; calls `player.relax()` when a sequence ends.

---

## 2026-08-04 — launchers + README

### `run.sh`
- Created. Starts backend and frontend together, installs dependencies on first run, opens the browser, and stops both on Ctrl+C.
- Preflights node/npm/python3 and refuses to start if port 8000 or 5173 is taken, printing the command to free it.
- Creates the venv at the **repo root**, not inside `backend/` — `uvicorn --reload` watches its working directory, and a venv in there triggers a reload storm over every site-package.
- Exits when either server dies, polled with `kill -0` rather than `wait -n` (macOS ships bash 3.2, which has no `-n`).

### `start.command`
- Created. Double-clickable Finder launcher; hands off to `run.sh`.

### `README.md`
- Created. Run instructions (one-click, one-command, manual), service table, worked examples, troubleshooting, project layout, and pointers to `PIPELINE.md` / `AGENTS.md`.

### `.gitignore`
- Added `.venv`, `venv`, `__pycache__/`, `*.py[cod]`.

---

## 2026-08-04 — visual cues + frontend refactor

### `src/ui/SignCaption.ts`
- Created. Red banner at the top of the screen naming the word being signed.
- Mapped words render whole with their gesture id beneath; spelled words render one span per letter, highlighting each as its gesture plays (`is-active`) and half-lighting the ones already signed (`is-done`).

### `src/sign/SignSegment.ts`
- Created. Shared `SignSegment` type — one source word plus the gestures that perform it.

### `src/sign/Sequencer.ts`
- Replaced the hardcoded 1800 ms delay with each motion's own `duration` from the manifest, plus a 0.12 s gap.
- Gestures with no clip hold for `MISSING_MOTION_SECONDS` (0.42 s) so fingerspelling captions still read at a sensible pace.
- `play()` now takes `SignSegment[]` instead of a flat gloss list.
- Added `SequencerListener` (`onSegmentStart` / `onGesture` / `onFinish`) so the caption follows playback without the Sequencer knowing what a caption is.
- Added a re-entrancy guard — a second `play()` mid-sequence would interleave gestures and desync the caption.

### `src/api/translate.ts`
- Returns `SignSegment[]` from the new `segments` field instead of the flat `gloss` list.
- Extracted the endpoint to a constant; error now includes the HTTP status.

### `src/ui/SignControls.ts`
- Restyled to `bar` / `bar__*` classes. Added `focus()`, empty-input guard, `aria-label`, and `role="status"` on the message line.

### `src/style.css`
- Full redesign: warm paper background, single brick-red accent, Helvetica Neue display stack paired with a mono stack for spelled letters, pill-shaped floating input bar, layered soft shadows, `prefers-reduced-motion` support.

### `src/main.ts`
- Wired up `SignCaption` and the sequencer listener; scene background matched to the page; three-light setup replacing the single key light.
- Input now disables during playback and reports translating / signing / done / error states.

### `backend/language/translator.py`
- Added `Resolution` dataclass so `spelled` is recorded when decided rather than inferred from gesture-list length (a one-letter word spells to a single gesture).
- Added `Segment` dataclass and `segment()`; `translate()` is now derived from it by flattening, so the two views cannot disagree.

### `backend/schemas.py`
- Added the `Segment` model and the `segments` field on `TranslateResponse`. Additive — `gloss` is unchanged.

### `backend/app.py`
- Endpoint builds both views from one `segment()` call. Dropped the `map_gloss` import.

### `backend/PIPELINE.md`
- Updated for `Resolution` and `Segment`; documented the segments contract extension.

---

## 2026-08-04

### `src/motion/MotionCatalog.ts`
- Added `id` to `MotionReference` — the gloss token, stamped on by `getMotion()`. This is the id `AnimationController` registers clips under; `motionId` is a dataset label and is not interchangeable with it.
- `getMotion()` now returns `MotionReference | null` instead of throwing, so a token with no clip skips one sign rather than aborting the sentence.

### `src/motion/DatasetLoader.ts`
- `LoadedMotion` carries `id` through to `MotionProcessor`.

### `src/motion/motion_manifest.json`
- Corrected all 9 `assetPath` values from `/public/animations/...` to `/animations/...`; Vite serves `public/` at the root.

### `src/sign/Sequencer.ts`
- Skips tokens with no registered motion, warning instead of crashing. Needed now that the translator emits fingerspelled `LETTER_*` / `DIGIT_*` tokens.
- Fixed the broken indentation in the play loop.

### `backend/PIPELINE.md`
- Created. Documents the recognise → map → resolve → replay workflow with diagrams and verified worked examples.

### `backend/language/translator.py`
- Redesigned around fingerspelling fallback. `translate()` is now recognise → resolve → replay.
- Added `spell()`: regex-splits a word into characters and returns one atomic gesture per character, mirroring the mapper's two-stage shape (distinct lookups, then ordered replay with duplicates intact).
- Added `resolve_vocabulary()`: maps distinct words via `mapper.map_recognition()`, and fingerspells any word that came back `UNMAPPED` instead of dropping it.
- Every word now resolves to a *list* of gestures — one element if mapped, one per character if spelled — so the replay step never branches on which happened.
- Stopped using `dictionary.json`; word resolution now comes from `mapper.py`/`vocabulary.json`. **`backend/language/dictionary.json` is now orphaned.**
- `translate()` still returns `list[str]`; the HTTP contract and frontend are unchanged.

### `backend/language/alphabet.json`
- Created. 36 character → atomic gesture entries (`a`–`z` → `LETTER_*`, `0`–`9` → `DIGIT_*`).
- Last-resort dictionary, consulted only for unmapped words.

### `backend/mapper.py`
- Rewrote around the `Recognition` dataclass. Added `MappedWord` (word + gesture pair) and `Mapping` (both views).
- `map_vocabulary()` resolves the distinct-word set only — one lookup per unique word, bounded by vocabulary size rather than input length.
- `map_sequence()` replays that result into written order with duplicates intact, performing no lookups of its own.
- `map_recognition()` returns both views; `to_gloss()` flattens to ordered gesture ids, dropping unmapped words by default.
- Added `DEFAULT_GESTURE = "UNMAPPED"` for words with no sign — distinct from `UNKNOWN`, which means the translator failed to understand the input.
- Kept `map_gloss()` as a legacy passthrough because `app.py` still imports it.

### `backend/vocabulary.json`
- Created. 24 word → gesture-id entries covering the 9 available signs plus synonyms.
- Loaded once at import by `mapper.py`, so mapping never touches the disk.

### `backend/language/recognizer.py`
- Replaced the `return [text]` stub with recursive paragraph → sentence → word splitting.
- Added the `Recognition` dataclass holding three views: `sentences` (grouped), `words` (flat, ordered), `vocabulary` (distinct).
- `recognize()` stores the ordered words and returns the distinct-word set; `split()` is a pure, stateless equivalent that returns all three views.
- Runs on raw text and normalises per word, because `TextNormalizer` strips the punctuation that sentence splitting depends on.

### `backend/language/translator.py`
- Reworked `translate()` to resolve-unique-then-replay-ordered: look up each distinct word once, then emit gloss in written order.
- Stopped normalising before recognition — raw text is now passed straight to the recogniser (see above).
- Dropped the now-unused `TextNormalizer` import; the recogniser owns normalisation.
- `translate()` still returns `list[str]`, so the HTTP contract and the frontend are unchanged.

### `AGENTS.md`
- Created. Operating guide for AI agents: project summary, technical specification, repository layout, architectural contracts, known-broken state, and coding rules.
- Added so agents have a single authoritative brief and stop relying on the stale `HANDOVER.md`.

### `CHANGELOG.md`
- Created. Establishes the modification log required by `AGENTS.md` §5.
