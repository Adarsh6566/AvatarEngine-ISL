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

Nine stages. Extraction is shared with the `pipeline/` dashboard; everything
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

| sign | takes | frames | σ | canonical | best take | gain | jitter (canon / takes) | range kept |
|---|---|---|---|---|---|---|---|---|
| we | 21 | 72 | 0.4 | 0.9213 | 1.0027 | **+8.1%** | 0.0187 / 0.0271 | 88% |
| how_are_you | 21 | 81 | 0.6 | 0.7652 | 0.8269 | **+7.5%** | 0.0245 / 0.0270 | 88% |
| good_evening | 21 | 71 | 0.0 | 0.8104 | 0.8732 | **+7.2%** | 0.0134 / 0.0194 | 83% |
| hello | 21 | 61 | 0.0 | 0.8262 | 0.8808 | **+6.2%** | 0.0132 / 0.0164 | 85% |
| you_plural | 21 | 72 | 0.6 | 0.8774 | 0.9343 | **+6.1%** | 0.0124 / 0.0215 | 83% |
| they | 21 | 68 | 0.0 | 0.8384 | 0.8917 | **+6.0%** | 0.0178 / 0.0211 | 88% |
| pleased | 20 | 63 | 0.0 | 0.7160 | 0.7611 | **+5.9%** | 0.0153 / 0.0182 | 84% |
| good_morning | 21 | 64 | 0.6 | 0.7554 | 0.8011 | **+5.7%** | 0.0139 / 0.0179 | 84% |
| good_afternoon | 22 | 63 | 0.6 | 0.7579 | 0.8018 | **+5.5%** | 0.0154 / 0.0202 | 84% |
| good_night | 21 | 67 | 0.4 | 0.8723 | 0.9219 | **+5.4%** | 0.0175 / 0.0179 | 93% |
| thank_you | 21 | 60 | 1.0 | 0.6889 | 0.7234 | **+4.8%** | 0.0198 / 0.0220 | 90% |
| alright | 21 | 63 | 0.6 | 0.8819 | 0.9037 | **+2.4%** | 0.0154 / 0.0201 | 91% |

Every sign beats its own best take. Finger jitter is at or below the take median
everywhere. 83–93% of finger range of motion is retained.

`we` gains most in the whole set at +8.1%, and for the mirror of the reason
`alright` gains least: its takes disagree more, so the average has more to add
over any single performance. The three pronouns split 0.48–0.58, inside the band
the greetings already occupy — the same unresolved question noted under
*Known limitations*, not a new one.

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
chest — inherits that.

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
| `offline/canonical/build.py` | orchestration, width selection, scoring, report |
| `offline/output/canonical/report.json` | every metric, per sign |
