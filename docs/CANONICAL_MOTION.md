# Canonical motion: what the model is, what it measures, and why

How the twelve signs in `public/skeleton/` are produced from 253 recorded takes.

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

The dataset is 253 sequences across 12 classes — roughly 21 takes per sign. A
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
| Source | ISL Greetings set, `Greetings_1of2` + `Greetings_2of2`; Pronouns set, `Pronouns_2of2` |
| Signs | 12 |
| Takes | 253 total (21–22 per sign) |
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
A take is rejected if more than 2% of frames have a wrist missing or pinned at
the origin. MediaPipe emits a joint for every frame whether or not it saw one,
so an absent hand appears as a degenerate value rather than a gap — and those
frames do not make the average noisier, they make it *wrong*, dragging it toward
wherever the tracker last guessed.

**One take rejected across the whole set:** `pleased/MVI_9955`, 6.8% dropout.

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
positions**, because the output has to stay in the space the runtime plays.

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

Result across all twelve signs: worst-case hand rotation falls from **118–177°
per frame to 28–36°**, and frames above the human limit go from 1.6–6.2% to
**0.0%**. Median rotation is unchanged (2.7° → 2.9°), so ordinary motion passes
through untouched, and finger range of motion went *up* rather than down.
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

### Results, all twelve signs

| sign | takes | frames | σ | canonical | best take | gain | jitter (canon / takes) | range kept | hand frames repaired |
|---|---|---|---|---|---|---|---|---|---|
| we | 21 | 72 | 0.6 | 0.9010 | 0.9954 | **+9.5%** | 0.0179 / 0.0261 | 91% | 22% |
| how_are_you | 21 | 81 | 0.6 | 0.7642 | 0.8407 | **+9.1%** | 0.0255 / 0.0271 | 88% | 11% |
| good_morning | 21 | 64 | 0.0 | 0.7379 | 0.8019 | **+8.0%** | 0.0128 / 0.0193 | 81% | 19% |
| you_plural | 21 | 72 | 0.6 | 0.8690 | 0.9355 | **+7.1%** | 0.0129 / 0.0201 | 85% | 12% |
| they | 21 | 68 | 0.0 | 0.8246 | 0.8847 | **+6.8%** | 0.0181 / 0.0218 | 88% | 17% |
| pleased | 20 | 63 | 0.0 | 0.7102 | 0.7614 | **+6.7%** | 0.0140 / 0.0185 | 83% | 19% |
| good_evening | 21 | 71 | 0.0 | 0.8121 | 0.8691 | **+6.6%** | 0.0131 / 0.0199 | 88% | 19% |
| hello | 21 | 61 | 0.0 | 0.8406 | 0.8941 | **+6.0%** | 0.0124 / 0.0170 | 84% | 18% |
| good_afternoon | 22 | 63 | 0.0 | 0.7642 | 0.8055 | **+5.1%** | 0.0189 / 0.0200 | 92% | 17% |
| good_night | 21 | 67 | 0.6 | 0.8960 | 0.9334 | **+4.0%** | 0.0180 / 0.0182 | 88% | 25% |
| thank_you | 21 | 60 | 1.4 | 0.7053 | 0.7334 | **+3.8%** | 0.0193 / 0.0231 | 89% | 14% |
| alright | 21 | 63 | 0.4 | 0.8884 | 0.9075 | **+2.1%** | 0.0179 / 0.0195 | 92% | 15% |

Every sign beats its own best take. Finger jitter is at or below the take median
everywhere. 81–92% of finger range of motion is retained.

`we` gains most in the whole set at +9.5%, and for the mirror of the reason
`alright` gains least: its takes disagree more, so the average has more to add
over any single performance. The three pronouns split 0.45–0.52, inside the band
the greetings already occupy — the same unresolved question noted under
*Known limitations*, not a new one.

The last column is how much of the capture the hand repair (stage 8) had to
rebuild. It runs at 11–25% per sign, and the worst single take in the set needed
96%: one recording where the tracker never held a stable palm at all.

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

### Keep the outlier session
One recording session (`01xx`) sits ~1.8 from the others where they sit ~1.1
among themselves, on *every* sign — the signature of a capture artefact rather
than a linguistic variant, which would differ per sign.

An ablation was run with the criterion fixed in advance: *drop it only if that
helps against both the full set and the majority subset*. It helped only against
the subset it was fitted to (circular) and **hurt** against the full population
on 3 of 4 signs tested. **Kept.**

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

**Vocabulary is 12 signs.** This is the binding constraint on everything
downstream. Any real sentence will contain mostly words with no sign, and they
are skipped silently. The pipeline scales linearly — one video, one extraction,
one library row per sign — but nothing about the method shortens that.

**Every sign has a high split score (0.48–0.71).** All twelve have takes that fall
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

**The avatar's proportions do not match the signers.** Forearm 1.31×, full arm
1.19×, against a torso that matches within 2%. Because retargeting copies
rotations, the hand lands at the end of a longer limb: measured 0.11–0.16
hips→head units too low at rest, which is what drives hands into the thighs.
Unrelated to the averaging — it would affect a single take identically — and
fixable with position-aware retargeting (two-bone IK), which is not built.

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
| `offline/canonical/hands.py` | palm-flip detection and hand repair |
| `offline/canonical/build.py` | orchestration, width selection, scoring, report |
| `offline/output/canonical/report.json` | every metric, per sign |
