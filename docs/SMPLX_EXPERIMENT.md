# SMPL-X experiment (additive)

An **experimental**, side-by-side alternative to the VRM avatar. It renders the
**exact same captured motion** (`public/skeleton/<sign>.json`) on an SMPL-X body,
so we can compare the two representations — proportions, joints, hand
articulation, signing readability — on identical input.

**It changes nothing in the working system.** The VRM path (`SkeletonRetargeter`,
`VrmRenderer`, `SignLibrary`, every `public/skeleton/*.json`, the index/signer/
lecture pages, the Android build, `config.yaml`, `vite.config.ts`) is untouched.
Everything here is new files under `offline/smplx/`, `frontend/smplx*`,
`public/smplx/`, and this doc.

## Data flow

```
public/skeleton/<sign>.json   (existing motion — UNCHANGED)
      │  59 joint POSITIONS/frame, view space (Y-up, hip-rooted, unit = hip→head)
      ▼
offline/smplx/skeleton_to_smplx.py   ADAPTER: positions → SMPL-X local rotations
      │  (same swing-extraction math as SkeletonRetargeter.ts)
      ▼
offline/smplx/build_glb.py   + SMPLX_NEUTRAL.npz (numpy, no torch)
      │  rest mesh + skeleton + skin weights + rotation animation
      ▼
public/smplx/<sign>.glb   skinned, animated glTF
      ▼
frontend/smplx.html + frontend/smplx/main.ts   interactive three.js viewer
```

The linear-blend-skinning "forward" runs **in the browser** via standard glTF
skinning — so the offline step needs **no torch, no GPU, no `smplx` package**,
only numpy + pygltflib.

## How motion is converted

The conversion is deliberately the **same method the VRM path uses**, so the
comparison is between the two *bodies*, not two different algorithms:

- **Swing extraction.** For each driven bone: `restDir` = direction to its child
  in the SMPL-X rest skeleton; `obsDir` = direction between the corresponding
  source joints; local rotation `q = fromUnitVectors(restDir, Rparent⁻¹·obsDir)`,
  walking parents→children. Identical to `SkeletonRetargeter`.
- **Wrist roll (palm facing).** The wrist additionally takes a second axis across
  the knuckles (index→pinky) to fix palm orientation — same construction as the
  VRM path's `orientationBetween`.

### Coordinate system & handedness

- Source is **view space**: Y-up, root-centred at the hips, unit = mean hip→head.
- A single **alignment rotation `R_align`** maps source vectors into SMPL-X's rest
  frame. It's built from anatomical axes in *both* frames — `up` = pelvis→head,
  `lateral` = left→right shoulder, `forward` = up×lateral — and matched. This is
  robust to whatever axis convention SMPL-X ships and, by matching `lateral`
  left→right, maps **source-left → SMPL-X-left** (same handedness choice as the
  working VRM path, which drives VRM-Left from source `l*`). No mirroring.
- Verified numerically: after conversion, posed SMPL-X bone directions match the
  observed directions with mean cosine **1.0000** on `we`.

## Joint mapping (source 59 → SMPL-X 55)

| Source | SMPL-X joint(s) | Driven by (direction) |
|---|---|---|
| `lShoulder`/`rShoulder` | `left_shoulder`(16)/`right_shoulder`(17) | shoulder→elbow |
| `lElbow`/`rElbow` | `left_elbow`(18)/`right_elbow`(19) | elbow→wrist |
| `lWrist`/`rWrist` + `lHand` | `left_wrist`(20)/`right_wrist`(21) | hand→middle-knuckle, + index→pinky roll |
| `lIndex1..4` | `*_index1,2,3` | 1→2, 2→3, 3→4 |
| `lMiddle1..4` | `*_middle1,2,3` | 1→2, 2→3, 3→4 |
| `lRing1..4` | `*_ring1,2,3` | 1→2, 2→3, 3→4 |
| `lPinky1..4` | `*_pinky1,2,3` | 1→2, 2→3, 3→4 |
| `lThumb1..3` | `*_thumb1` | thumb1→thumb2 |

(SMPL-X hand order is index, middle, **pinky, ring**, thumb — mapping is by name,
not position.) Root/`global_orient` is identity (upright), matching the VRM default.

## What is NOT mapped (documented, not silently discarded)

- **Torso, spine, neck, head, legs/feet.** The source *does* carry these joint
  positions, but the VRM path holds them at rest for a signing avatar
  (`driveBody`/`driveLegs` off by default). We match that so the comparison is
  like-for-like. Enabling them later is straightforward (add drives).
- **Thumb intermediate/distal** (`*_thumb2`, `*_thumb3`) — left at rest, mirroring
  the VRM path (its thumb distal rest is angled, which flips the straight-digit
  assumption). Thumb proximal only.
- **Bone twist** about a bone's own axis — not recoverable from joint positions
  (swing-only). Same limitation as the VRM path. Wrist roll is the one exception
  (recovered from the knuckle fan).
- **Facial motion** — the skeleton JSON contains no facial data, so SMPL-X's
  jaw/eyes/expression stay neutral. (Facial capture exists elsewhere in the
  pipeline but is not in these clips.)
- **SMPL-X pose-corrective blendshapes** — omitted, because the bake is LBS-only
  (a single rest mesh + skin weights, skinned in-browser). Expect slightly more
  linear-blend-skinning creasing at sharply bent joints than "true" SMPL-X. Adding
  them would mean per-frame morph targets (much larger files) or an offline
  torch bake.

## Arm IK + hand clearance (parity with the VRM)

Both corrections from the VRM path are ported to the adapter (offline), so the
SMPL-X body gets the same treatment the VRM does and the comparison stays fair:

- **Arm IK** (`armIK.ts`). Copying rotations onto a differently-proportioned arm
  moves the hand off target, so the elbow is *solved* (law of cosines) to put the
  SMPL-X **wrist on the signer's target** for SMPL-X's own arm lengths. This is
  the primary correction and it is exact (self-check stays 1.0).
- **Hand clearance** (`handClearance.ts`). The two wrists are pushed apart along
  the smoothed closest-pair axis until the hands stop interpenetrating, then the
  elbows re-solve. Verified across all 17 signs: it never makes any sign worse,
  and on `we` the closest hand-to-hand distance goes from **0.47 cm to 1.62 cm**.

**Honest limit.** SMPL-X's hands are anatomically larger and interleave more
deeply than the VRM's on the most crossing signs (`we`, `thank_you`), where the
fingers interpenetrate in several directions at once. No single rigid wrist push
can fully separate interleaved fingers, so a little residual overlap can remain
there — itself an informative result (a realistic hand model overlaps more than a
stylised one at the same captured wrist positions). The push cap is raised from
the VRM's 0.09 to **0.13** hip->head units to compensate; the push is
depth-dominant — the axis a single camera could not measure — so it is far less
visible than its size suggests.

Toggle either off in the adapter (`compute_rotations(..., arm_ik=False)` /
`hand_clearance=False`) to compare.

## Temporal smoothing

The per-frame swing extraction (and the clearance push switching on and off
between frames) leaves the raw motion jittery, so a **zero-phase slerp smoother**
runs on the final rotations — a slerp EMA applied forward then backward, so it
removes jitter with **no lag** (better than the signer's causal `fingerSmoothing`,
which it can afford because this is an offline bake). The arms smooth harder than
the fingers, because the wrist carries the whole hand so wrist jitter shakes the
fingertips regardless of finger smoothing. On `we` this removes **~59% of the
fingertip jitter while keeping ~86% of the range of motion**. Turn it off with
`compute_rotations(..., smooth=False)`; tune `SMOOTH_FINGER` / `SMOOTH_ARM`.

## How to run

**1. Place the model** (once): `pipeline/.models/smplx/SMPLX_NEUTRAL.npz`
(register at smplx.is.tue.mpg.de — non-commercial licence).

**2. Install the isolated deps** (once):
```
python -m pip install -r offline/smplx/requirements.txt
```

**3. Bake a sign to a GLB:**
```
python offline/smplx/build_glb.py --sign we
```
Writes `public/smplx/we.glb`. Prints a `self_check_mean_cos` (≈1.0 = correct).

**4. View it** (dev): with the frontend dev server running (`npm --prefix frontend
run dev`), open **http://localhost:5173/smplx.html** (or `?sign=we`). Drag to
orbit, scroll to zoom; Play / Pause / Restart / speed; the sign dropdown lists
every library sign (unbaked ones show the command to bake them).

> Not yet wired into the production build (`vite.config.ts` unchanged) — dev-only
> for now, by design.

## Current limitations

- All 17 signs baked; the legs and lower torso are cropped at the belt in the
  bake (arms/hands always kept, by skinning joint).
- Arm IK + hand clearance are applied; residual hand overlap can remain on the
  most deeply-crossing signs (see *Arm IK + hand clearance* above).
- LBS-only (no pose blendshapes).
- Neutral body shape (`betas = 0`); not fitted to any signer.
- If the body faces away on load, orbit around it (facing follows SMPL-X's rest
  frame; no root reorientation is baked in).
