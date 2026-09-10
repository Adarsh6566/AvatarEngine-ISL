# Canonical motion: what the model is, what it measures, and why

How the seventeen signs in `public/skeleton/` are produced from 358 recorded takes.

Written to be checkable: every number here is emitted by
`offline/canonical/build.py` into `offline/output/canonical/report.json`, and
every decision records the measurement that settled it.

---

## What this is, stated plainly

**It is not a trained neural network, and it has no accuracy score.**

That is worth saying first because "machine learning model" usually implies
both. This is *unsupervised template estimation*: given N recordings of the same
sign, produce the one sequence that best represents them. There are no labels,
no train/test split, no classification, and no learned parameters — so
precision, recall and accuracy have nothing to attach to.

The algorithm is **DTW Barycenter Averaging** (DBA, Petitjean et al. 2011).

### Why not a network

The dataset is 329 screened sequences across 17 classes — roughly 21 takes per sign. A
generative motion model with enough capacity to represent signing would have
more parameters than it has frames to fit, and would memorise the takes rather
than generalise from them. Averaging has no parameters to overfit, so at this
scale it is the stronger method, not the fallback.

That judgement is tied to the data volume, not to the approach being wrong in
principle. At hundreds of signs with tens of thousands of sequences, a learned
motion prior becomes the better tool and this document should be revisited.

---

## Data

| | |
|---|---|
| Source | ISL Greetings set, `Greetings_1of2` + `Greetings_2of2`; Pronouns set, `Pronouns_1of2` + `Pronouns_2of2` |
| Signs | 17 |
| Takes | 358 recorded, 329 used (18–21 per sign after screening) |
| Signers | at least 3 recording sessions, different people, different rooms |
| Video | 1920×1080, 25 fps, 2–4 s per take |
| Output | 59 joints/frame, 25 fps, `source_skeleton.v1 → view` |

Takes per sign vary because the source folders do; `good_afternoon` has 22, the
rest 21, and `pleased` ships 20 after one rejection. The three pronouns lost no
takes at all — every one of their 63 recordings passed the quality screen.

---

## Pipeline

Ten stages. Extraction is shared with the `pipeline/` dashboard; everything
from stage 4 lives in `offline/canonical/`.

### 1. Pose extraction — MediaPipe Tasks
`pose_landmarker_lite.task` + `hand_landmarker.task`, per frame, giving body
pose and 21 landmarks per hand. Output is 2.5D: X and Y are image-plane and
reliable, Z is inferred and is the weakest channel in the whole system.

### 2. Normalisation to view space
Y-up, root-centred at the hips, scaled so mean hip→head is 1. This is what makes
takes from different signers at different distances comparable at all: body size
and camera distance divide out.

### 3. Per-joint smoothing
`pipeline/extractor/smooth.py`, heavier on the spine, lighter on the hands.

### 4. Quality screen
Two rejections, both asking whether a take was *measured*, not whether it was
performed well.

A take is rejected if more than 2% of frames have a wrist missing or pinned at
the origin. MediaPipe emits a joint for every frame whether or not it saw one,
so an absent hand appears as a degenerate value rather than a gap — and those
frames do not make the average noisier, they make it *wrong*, dragging it toward
wherever the tracker last guessed.

**One take rejected on that criterion:** `pleased/MVI_9955`, 6.8% dropout.

A take is also rejected if more than **half its frames** fail the hand rate test
of stage 10 — the palm was never solved, so repairing it would mean inventing
most of the performance rather than mending it. This rejects **27 takes**, mostly three
per sign, and they are the systematic outlier session; see *Decisions*. The
separation is clean: rejected takes need 51–98% of frames rebuilt, kept takes
2–28%.

### 5. Alignment features
DTW needs a per-frame vector to compare. It is built as:

- arm joints (shoulder, elbow, wrist, hand) in absolute view coordinates
- finger joints **relative to their own hand root**, weight 1.0

The hand-relative part matters more than it looks. Finger joints are absolute
too, so all forty of them carry the arm's trajectory and contribute it again;
the articulation itself — a couple of centimetres against half a metre of arm
travel — vanishes in the sum. Aligning on raw positions therefore matches takes
by *when the arm rose*, not *when the hand opened*, and averaging under that
warp blends open hands into closed ones.

### 6. DTW barycenter averaging
- **Init:** the medoid take, resampled to the median take length. Seeding from
  the medoid rather than an arbitrary take matters because DBA descends to a
  local optimum — starting from an outlier converges to a shape no signer
  performed.
- **Iterate:** warp every take onto the current reference, then set each
  reference frame to the trimmed mean (drop the most extreme 20%) of the frames
  mapped onto it.
- **Stop:** mean absolute change below 1e-5, or 12 iterations. Observed
  convergence: 6–12 iterations depending on the sign.

Alignment runs on the features from stage 5; **averaging runs on raw joint
positions**, because the output has to stay in the space the runtime plays —
*except for the hands*, which are averaged as rotations.

A positional mean folds fingers. It is the same fault the pipeline already
corrects for bone lengths in stage 9, but stage 9 cannot see this one: it fixes
each bone's length while leaving the chain's joint angles averaged, so every
bone comes out the right length and the whole finger sits curled tighter than
any take performed. On `they` the takes hold the four fingers at 0.84 / 0.74 /
0.84 / 0.88 straightness and the positional mean returned **0.96 / 0.70 / 0.97 /
0.98** — three fingers pulled straight and one left bent, which is not a
handshape anyone signed. Elsewhere in the same clip the index reached 0.15
against a tightest take of 0.55.

So for each reference frame the hand is rebuilt from the mean of its members'
*rotations*: the hand's orientation as an averaged quaternion, each finger bone
as an averaged unit direction in that frame, lengths from the median. That keeps
the result on the manifold of poses a hand can hold. `they` now returns 0.87 /
0.72 / 0.85 / 0.90 against the takes' 0.84 / 0.74 / 0.84 / 0.88, and
`you_plural` keeps the index-versus-rest separation that makes it a pointing
sign at all.

### 7. Despiking
A 3-frame running median. The barycenter's worst artefact is not its general
noise level but a handful of frames jumping several times the median step —
measured up to 7.6× on a wrist. A Gaussian cannot remove an impulse, it spreads
it across the neighbours, which is why widening the smoothing width did not
help. A running median discards it outright and leaves genuine fast movement,
which the surrounding frames corroborate.

### 8. Temporal smoothing
A narrow Gaussian, width auto-selected per sign (see *Decisions*). Removes the
residual roughness DBA introduces where warp membership changes abruptly
between adjacent reference frames.

### 9. Bone-length enforcement
Median bone lengths are restored by walking the joint hierarchy. Averaging
positions independently does not preserve a skeleton: the mean of two elbows
bent different ways sits closer to the shoulder than either, so forearms shrink
on exactly the frames where takes disagree most.

### 10. Hand repair
MediaPipe solves each frame independently, and a hand that is moving or seen
edge-on is genuinely ambiguous — palm-toward and palm-away fit the same
silhouette. The tracker picks one per frame and oscillates, so the palm inverts
between consecutive frames. Measured across the 253 takes, **4.5% of frames turn
the hand more than 90° in a single 1/25 s step, and the worst reaches 179.6°.**

No wrist can do that; pronation and supination peak near 1000°/s even in fast
athletic movement. Frames claiming more than **900°/s** are treated as a failed
solve. The hand's *position* is kept exactly as captured — it is carried by the
arm, and the body pose estimate is the reliable channel. What is rebuilt is the
hand's orientation and the direction of each finger bone in the hand's own
frame, interpolated across the bad frames from the nearest accepted ones on
either side.

Three things this stage had to get right, each found by measurement:

**It is not more smoothing.** Despiking and the Gaussian both run before it and
neither removes the artefact — a median cannot fix a flip that lasts two frames,
and a Gaussian averages the flipped pose into its neighbours instead of
discarding it. The rate test is the only stage that asks whether a frame is
physically possible at all.

**Repairing the takes is not enough.** Cleaning all 21 inputs still left the
barycenter swinging 177° between two frames: positions are averaged per joint,
which does not preserve a rotation, so where warp membership changes between
adjacent reference frames the mean hand frame jumps. The repair runs on the
takes *and* on the result.

**It interpolates rotations, never positions.** Lerping a repaired frame between
two trusted ones collapsed a bone by 82% — the same failure this pipeline
already documents for averaging elbows. Carrying the handshape as one unit
direction per bone and re-applying median lengths makes bone length exact by
construction.

Ordering follows from that last point: this stage runs **after** bone-length
enforcement, not before. Enforcing lengths rescales each knuckle independently
from the hand, which swings the index→little vector the palm's roll is measured
against and put the flip straight back — 33°/frame became 171° again.

**The fingers need their own test, and a different one.** Stabilising the palm
says nothing about articulation. With the hand frame divided out, single finger
bones were still measured snapping **178.9° between frames**, 6.1% of them above
30°/frame — which is what reads as fingers moving on their own and crossing into
each other. Each bone gets a rate ceiling of **700°/s** against its own direction
in the hand frame: rapid finger tapping tops out near 800°/s and signing is not
tapping.

But a finger is **slowed, not replaced**. The wrist's test discards a frame
outright, because a flipped palm is a pose the hand never held and interpolating
past it is the only honest option. A finger moving too fast is a different
failure: the pose it is moving *toward* is usually right and only the speed is
wrong. Discarding those frames threw the destination away — on `it` the hand
opens hard over two frames and is then held, and rejecting the opening
interpolated straight across the hold, leaving 0.38 / 0.41 straightness on the
middle and ring fingers where every take shows 0.90 / 0.92. A slew limit turns
toward the observed direction as fast as a finger can manage and no faster, so it
arrives at the real pose and holds it.

**Damping comes before the limit, not after.** The barycenter carries steps no
take does, because warp membership changes between adjacent reference frames: on
`it`, one bone turns 147° in a single frame immediately before the held pose. A
Gaussian on directions ramps a step and leaves a plateau alone, which gives the
limiter a slope to follow instead of a cliff it can never catch up with. Run the
other way round, the limiter met the cliff first and was still climbing when the
hold arrived. The width is the per-sign σ with a floor of 1.2 frames, since σ is
chosen on whole-clip jitter and a single-frame step barely moves that.

Swept together across eight signs, this pair is the operating point: widening the
Gaussian erodes the peak (mean handshape error 0.048 → 0.063 at width 2.5), and
loosening the rate ceiling to 1600°/s buys 0.007 of accuracy while doubling the
worst finger rate to 64°/frame, which is the flailing the whole stage exists to
remove.

**An undetected hand is not a noisy one.** MediaPipe emits a joint whether or not
it found one, so a hand it never saw comes back with every finger collapsed onto
the wrist — **10.5% of all frames**, and 15% of takes open on one. A collapsed
bone has no direction at all; normalising it gives NaN or an arbitrary axis. Such
frames can never be trusted and, more importantly, can never be an endpoint to
interpolate *from*. The walk is seeded at the first frame that passes rather than
at frame 0, which is where the first version anchored 15% of takes to a pose that
did not exist.

Result across all seventeen signs: worst-case wrist rotation falls from **118–177°
per frame to 12–28°**, worst-case finger swing from **94–179° to 11–28°**, and
frames above the human limit go from 1.6–6.2% to **0.0%**. Finger range of motion
went *up* rather than down.
---

## What is measured, and the results

### The metric

**Mean warped distance from a candidate sequence to every take**, computed in
raw joint space over arm and finger joints, normalised by DTW path length.

Lower is better. It is the quantity DBA minimises, and it means "how well does
this one sequence represent the whole set". The baseline it is compared against
is the **best single take** — the individual recording that scores best by the
same measure — because that is what the system shipped before, and beating it is
the claim being made.

Scoring stays in raw joint space even though alignment uses features. Grading
alignment features in their own space would only prove they optimise themselves.

### Results, all seventeen signs

| sign | takes | frames | σ | canonical | best take | gain | jitter (canon / takes) | range kept | hand frames repaired |
|---|---|---|---|---|---|---|---|---|---|
| good_evening | 18 | 65 | 0.6 | 0.6810 | 0.7622 | **+10.7%** | 0.0169 / 0.0201 | 91% | 8% |
| she | 21 | 68 | 1.0 | 0.7890 | 0.8727 | **+9.6%** | 0.0167 / 0.0216 | 98% | 11% |
| good_morning | 19 | 63 | 0.0 | 0.6676 | 0.7309 | **+8.7%** | 0.0139 / 0.0184 | 82% | 13% |
| it | 20 | 54 | 0.0 | 0.8664 | 0.9429 | **+8.1%** | 0.0135 / 0.0157 | 79% | 12% |
| he | 20 | 65 | 0.0 | 0.7675 | 0.8334 | **+7.9%** | 0.0140 / 0.0202 | 101% | 11% |
| we | 18 | 59 | 0.0 | 0.7396 | 0.8031 | **+7.9%** | 0.0284 / 0.0297 | 92% | 14% |
| how_are_you | 21 | 81 | 0.0 | 0.7863 | 0.8363 | **+6.0%** | 0.0210 / 0.0260 | 89% | 11% |
| you | 21 | 63 | 0.0 | 0.7939 | 0.8431 | **+5.8%** | 0.0107 / 0.0179 | 90% | 9% |
| i | 20 | 59 | 0.4 | 0.6774 | 0.7156 | **+5.3%** | 0.0131 / 0.0168 | 90% | 7% |
| good_afternoon | 19 | 63 | 0.0 | 0.6663 | 0.7002 | **+4.8%** | 0.0187 / 0.0202 | 92% | 9% |
| alright | 18 | 61 | 0.8 | 0.6910 | 0.7231 | **+4.4%** | 0.0119 / 0.0210 | 84% | 6% |
| pleased | 18 | 60 | 0.0 | 0.6260 | 0.6542 | **+4.3%** | 0.0184 / 0.0205 | 88% | 13% |
| they | 21 | 68 | 0.0 | 0.8464 | 0.8815 | **+4.0%** | 0.0198 / 0.0214 | 94% | 16% |
| you_plural | 18 | 72 | 1.4 | 0.7615 | 0.7835 | **+2.8%** | 0.0118 / 0.0211 | 84% | 5% |
| thank_you | 20 | 58 | 2.0 | 0.6623 | 0.6790 | **+2.5%** | 0.0188 / 0.0249 | 89% | 11% |
| hello | 19 | 56 | 0.6 | 0.7255 | 0.7359 | **+1.4%** | 0.0163 / 0.0170 | 88% | 13% |
| good_night | 18 | 61 | 0.6 | 0.7625 | 0.7658 | **+0.4%** | 0.0171 / 0.0190 | 84% | 14% |

Every sign beats its own best take. Finger jitter is at or below the take median
everywhere. 79–101% of finger range of motion is retained — `he` above 100%
because rotation averaging can hold a handshape the median take does not.

Gains are lower than an earlier build reported, and that is the trade this
version takes deliberately. The score measures how well one sequence represents
the set; it does not ask whether the pose is a handshape anyone can make. Where
the two disagree — on the frames a sign is actually held — this version keeps the
handshape. `good_night` at +0.4% and `hello` at +1.4% are the signs that paid
most for it; both were already the least improved, because their takes agree
closely enough that averaging has little to add over a good single performance.

Gains are smaller than they were before the hand work, and that is the expected
direction: the baseline moved. Both the canonical and the "best single take" it
is measured against are now scored over 18–21 screened takes rather than 21
unscreened ones, so the comparison no longer gets credit for beating recordings
whose hands were never tracked.

The last column is how much of the capture the hand repair (stage 10) had to
rebuild on the takes that survived screening: 5–16% per sign.

The five singular pronouns added last score among the best in the set — `she`
leads it at +11.5%, and `he`, `she` and `you` retain 93–98% of finger range,
more than any greeting. They are short, single-handed, and shot in one session
each, so the takes agree closely and there is less for the warp to reconcile.
`it` is the exception at 75% range retained, the lowest anywhere: it is the
shortest clip in the set at 54 frames, and averaging has least room to preserve
a brief handshape.

`alright` gains least at +2.4% because its takes are the most consistent of the
nine — when the recordings already agree, averaging has least to add over a good
single performance. That is the expected shape of the result, not a fault.

### Secondary measures

- **spread** — mean pairwise warped distance between takes. How much the
  signers disagree.
- **split score** — quality of the best two-way split, `(between − within) /
  between`. Near 0 means one population; high means two distinct *variants*,
  where averaging is the wrong operation because it interpolates between two
  correct performances to produce a third that is neither.
- **finger jitter** — median per-frame fingertip movement.
- **range retained** — canonical finger range of motion over the takes' median.

---

## Decisions, and the evidence for them

Each of these was settled by measurement, and several overturned the first
answer.

### The outlier session — kept, then dropped on better evidence
One recording session (`MVI_0079`–`MVI_0116`) sits ~1.8 from the others where
they sit ~1.1 among themselves, on *every* sign — the signature of a capture
artefact rather than a linguistic variant, which would differ per sign.

It was originally **kept**. An ablation with the criterion fixed in advance —
*drop it only if that helps against both the full set and the majority subset* —
helped only against the subset it was fitted to (circular) and hurt against the
full population on 3 of 4 signs.

That is now **overturned**, because the hand rate test explains what the distance
metric could only describe. Those takes are the ones where hand tracking failed:
they need **51–98% of their frames rebuilt**, against 2–28% for every other take
in the set, and the gap is clean with nothing in between. Three takes per sign,
25 in total.

The old ablation could not have seen this. It scored candidate templates by mean
warped distance *to the full population, including these takes* — so a template
dragged toward badly-tracked hands scored well precisely because the bad hands
were in the reference. The question it asked, "does dropping them improve the fit
to everything", cannot distinguish a variant from a broken measurement. The rate
test asks a different question with an outside answer: was this pose physically
possible at all.

Dropped. 27 of 358 takes, leaving 18–21 per sign.

### Finger weight 1.0, not higher
Swept 0 / 1 / 2 / 4 on `pleased`, scored in raw joint space:

| weight | vs best take | flower peak retained |
|---|---|---|
| 0 (raw positions) | +5.9% | 93.5% |
| **1.0** | **+7.1%** | **96.3%** |
| 2.0 | +6.5% | 95.1% |
| 4.0 | +6.1% | 97.1% |

1.0 beat the old behaviour on both measures. Heavier weights traded score away
as the warp began chasing finger noise — the same noise the runtime damps at
0.9.

### Smoothing width chosen per sign, on four statistics
The width is the smallest on a fixed ladder that leaves the canonical no
jitterier than a typical take, judged on **median and 95th-percentile step, for
both fingers and the arm**.

The first version checked fingers and the median only. That was wrong twice: it
never looked at the wrist, which was the worse offender, and satisfying a median
says nothing about lurches. Worse, adding despiking lowered the median, which
under the old rule caused *less* smoothing to be selected and the jumps to grow
— caught only because the numbers came back worse after a change meant to
improve them.

### `pleased` ships the average, not a chosen take
`pleased` has the widest disagreement in the set: peak fingertip spread runs
0.37 to 0.93 across its takes, a 2.5× range at a split score of 0.618. It was
briefly shipped as a single hand-picked take on the grounds that averaging
flattened the opening.

That was **reverted at the user's instruction**, and correctly: hand-picking is
not what the pipeline is for, and a per-sign exception would have made the nine
clips inconsistent in how they were produced. All nine are now averaged the same
way.

The underlying finding still stands and is unresolved: even restricted to the
seven takes that perform the full opening, the barycenter peaked at 0.61 against
their median 0.83. A brief high-amplitude peak is eroded by averaging peaks that
differ slightly in timing, however well the warp is tuned.

### Playback interpolates between frames
Not part of the model, but it decides how the model's output looks. Clips are 25
fps and displays run at 60; the player took `frames[floor(cursor)]`, holding
each pose for two or three refreshes and then jumping. Largest movement between
two *rendered* frames on `thank_you`: **0.144 snapping, 0.060 interpolating — a
58% reduction.**

---

## Known limitations

These are properties of the current system, not bugs with fixes pending.

**Vocabulary is 17 signs.** This is the binding constraint on everything
downstream. Any real sentence will contain mostly words with no sign, and they
are skipped silently. The pipeline scales linearly — one video, one extraction,
one library row per sign — but nothing about the method shortens that.

**Every sign has a high split score (0.45–0.75).** All seventeen have takes that fall
into two groups. `pleased` is the one where this was visibly wrong; the others
may carry the same problem in milder form. Whether each split is a capture
artefact or a genuine variant has not been established sign by sign — it needs
someone who reads ISL, not a distance metric.

**The averaging erodes brief high-amplitude peaks.** Established on `pleased`
and expected to apply anywhere a sign turns on a fast, short gesture.

**Capture under-elevates the arms.** At the peak of `pleased`, the extracted
wrist sits at 0.694 of the hips→head span — chin height — where the source video
clearly shows the hand beside the face. The retargeting reproduces the data to
within 8%, so this is lost in extraction, upstream of anything documented here.

**Depth is the weakest channel.** MediaPipe's Z is inferred from a single view.
Everything derived from depth — palm facing, how far a hand sits in front of the
chest — inherits that. Stage 10 removes the *impossible* part of this, the frames
where the palm solution flips outright, but it cannot recover a palm angle the
capture never saw: where the tracker is confidently wrong at a plausible rate,
the repair passes it through.

**The avatar's proportions do not match the signers — now corrected at
playback.** Measured against hip→head on the shipped clips: forearm **1.49×**,
whole arm **1.32×**, on shoulders only **1.06×** wider. Because retargeting
copies rotations, the hand lands at the end of a longer limb, somewhere the
signer's hand never was.

On `we`, where the arms cross in front of the chest, that was visible as the
hands passing through each other: the signers' wrists close to 0.119 hip→head
units and the rotation-only avatar carried them on to **0.048**, overlapping for
21 frames of 59.

`frontend/avatar/animation/armIK.ts` now solves the elbow instead of copying it.
The shoulder and the wrist are the constraints, the elbow is placed by the
cosine rule, and the observed elbow picks the swivel so the arm still bends the
way the signer's did. Each hand ends up where it was relative to its own
shoulder, and on `we` the wrists separate from 0.048 to **0.138**.

**That fixed the wrists and not the hands.** The 0.138 above is a wrist-to-wrist
number, and a wrist is a point while a hand is not: this rig reaches 10.5cm from
the wrist to a fingertip, and the sign brings the wrists to 7.1cm apart. Measured
through the real retargeter against the real rig, the two hands' BONES still
closed to **0.6cm** and overlapped on **23 frames of 59** — with the wrists a
correct 13.3cm apart the whole time. Measuring the wrong quantity is what let the
first fix report success.

The captured hands cannot settle it either. MediaPipe's hand landmarks arrive
about **3.4× too small** against the body — 0.077 hip→head units where this rig
is 0.262 — so the recorded fingers clear each other by 1.8cm at a scale where the
avatar's are deep inside each other. Only the avatar's own geometry says what
fits.

`frontend/avatar/animation/handClearance.ts` pushes the two wrist targets apart
by the smallest amount that clears the hands, and armIK re-solves both elbows for
the moved targets. Two properties make it exact rather than iterative:

- a hand's world **orientation** is the captured direction and nothing else — the
  rotation is built in the parent's frame and multiplied back by it, so the
  forearm cancels and a moved elbow cannot turn the hand. Each hand therefore
  translates **rigidly** with its wrist (verified: hand world rotation changes by
  3.4e-6°, finger rotations by 6.2e-6°),
- so along a fixed axis a pair separated by `d` ends up `|d + δu|` apart, which is
  one quadratic in δ per pair.

The axis is the **closest pair's own direction, smoothed**, and getting there took
two wrong answers. Pushing along the wrist axis is the obvious choice and clears
only 13 of the 21 frames, because the wrists are separated sideways while the
collision is almost entirely in **depth**: at the closest frames the pair
direction runs [-0.06, 0.12, **-0.99**] against a wrist axis of [0.86, -0.03,
-0.50]. That the collision is in depth is not chance — depth is the one axis a
single camera cannot measure, and the wrists hold only 2cm of it through the
cross, less than a hand is thick. Smoothing (0.25 per frame) is what makes the
pair direction usable: the closest pair jumps between bones frame to frame, and
an axis that jumps makes the hands judder.

| | before | after |
|---|---|---|
| `we` closest hand-to-hand | 0.6cm | **2.5cm** |
| `we` frames overlapping | 21 of 59 | **0** |
| `thank_you` | 0.6cm, 9 frames | **2.5cm, 0** |
| `alright` | 1.9cm, 3 frames | **2.5cm, 0** |
| the other 14 signs | — | **bit-identical** |

The clearance is measured from the rig rather than tuned: 1.35× the mean gap
between adjacent knuckles, which is a finger's width plus room for the palm
behind it — 2.5cm here. Worst wrist displacement across all seventeen is 2.4cm,
against a 4.8cm safety cap that no sign reaches. Cost is 0.007ms per frame.

This is a *playback* fix and lives in the frontend, not in this pipeline — the
clips are unchanged, and the same clips on a differently-proportioned avatar get
that avatar's solution. Pass `?ik=0` to compare against the old behaviour.

`cd frontend && npm test` checks all of this against the shipped `.vrm` and the
shipped clips: no sign overlapping, the fourteen non-colliding signs untouched,
handshapes unturned, no judder introduced, and the push solver exact over 4000
random point sets. That last one earned its place — solving each pair
independently and taking the largest root looks right and is not, because a push
one pair demands can drag a pair that was already clear back under. It passed all
seventeen clips and failed the random test at 4.51cm of 5.

Still open: the capture under-elevates the arms (above), which IK cannot
recover — it faithfully reaches the position that was measured, including when
that position is too low.

---

## Reproducing

```bash
# 1. extract every take to a view-space skeleton stream (cache dir of your choosing)
#    73s for 63 takes on 4 CPU workers
python -m offline.canonical.extract --source <recordings-dir> --cache <takes-dir>

# 2. average each sign's takes into one canonical clip
python -m offline.canonical.build --cache <takes-dir> --out offline/output/canonical
```

`--source` is the recording set as delivered: one directory per sign, named
`<number>. <words>`, holding one video per take. The directory name becomes the
sign's slug, so `46. you (plural)` writes `you_plural`.

Extraction reuses `pipeline/`'s MediaPipe extractor rather than reimplementing
it, so a take captured for the dashboard and a take captured for a canonical are
the same numbers. It skips takes already in the cache, which makes a re-run
after adding one sign cheap. Face capture is off: `write_stream` keeps only
joints, so the blendshapes would be computed and immediately discarded, and the
face landmarker is most of the per-frame cost.

`--sigma` pins the smoothing width instead of auto-selecting it; `--signs` limits
the run to named signs. The report lands in
`offline/output/canonical/report.json` with every number in this document.

Clips are copied to `public/skeleton/<sign>.json` by hand, per the offline
contract in `offline/README.md`: the offline pipeline never edits runtime files.

---

## Source

| File | Contents |
|---|---|
| `offline/canonical/extract.py` | video -> view-space take cache (stages 1-3) |
| `offline/canonical/takes.py` | loading, quality screen, alignment features |
| `offline/canonical/dba.py` | DTW, barycenter, despike, smoothing, bone lengths |
| `offline/canonical/hands.py` | hand screening, rotation averaging, palm and finger repair |
| `offline/canonical/build.py` | orchestration, width selection, scoring, report |
| `offline/output/canonical/report.json` | every metric, per sign |
