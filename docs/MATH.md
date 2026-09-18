# The mathematics behind the avatar

The avatar's signing motion is not animation — it is produced by a chain of
**geometry, optimisation, and signal-processing** steps applied to motion
captured from video. This document states each step three ways: the **technical
term**, the **mathematics**, and **why it is needed**. Formulas render on GitHub.

Pipeline order: normalise → align (DTW) → average (DBA) → average *rotations*
(SO(3)) → reject impossible frames → inverse kinematics → clearance → smooth.

---

## 0 · Normalisation — scale & translation invariance

Every take is re-expressed in a body-relative frame: root-centred at the hips,
scaled so the mean hip→head length is $1$.

$$x'_t = s\,(x_t - x^{\text{hip}}_t), \qquad s = \left(\frac{1}{T}\sum_{t=1}^{T}\big\lVert x^{\text{head}}_t - x^{\text{hip}}_t\big\rVert\right)^{-1}$$

**Why.** Takes from different signers, at different distances from the camera,
become directly comparable — body size and camera distance divide out.

---

## 1 · Dynamic Time Warping (DTW)

Signers perform at different speeds, so sequences are aligned in time by a
dynamic-programming recurrence over a cost matrix $D$:

$$D(i,j) = \lVert a_i - b_j\rVert^2 + \min\{\,D(i-1,j),\; D(i,j-1),\; D(i-1,j-1)\,\}$$

$$\mathrm{DTW}(A,B) = D(n,m), \qquad \text{cost } O(nm)$$

**Why.** Comparing or averaging frame-by-frame only makes sense once "the same
moment" in two performances is matched up. DTW finds that matching.

---

## 2 · DTW Barycenter Averaging (DBA) — a Fréchet mean

The canonical sign is the sequence minimising the sum of *squared* DTW distances
to all $K$ takes — a **Fréchet (barycenter) mean** under the DTW metric:

$$c^{*} = \arg\min_{c}\ \sum_{k=1}^{K} \mathrm{DTW}(c, s_k)^2$$

Solved by **Lloyd-style iteration** (as in $k$-means): warp every take onto the
current reference $c$, then set each reference frame to the **20 %-trimmed mean**
of the take-frames assigned to it. Seeded from the **medoid**

$$s_{\text{med}} = \arg\min_{k}\ \sum_{j} \mathrm{DTW}(s_k, s_j)$$

and iterated to a local optimum (≤ 12 iterations in practice).

**Why.** One recording carries one signer's quirks and the tracker's noise.
The barycenter is the single motion that best represents the whole set — and
empirically it beats every sign's own best single take.

---

## 3 · Rotation averaging on SO(3) — average orientations, not positions

Hands are averaged as **orientations**, not point coordinates. Given unit
quaternions $q_1,\dots,q_K$ with weights $w_k$, the (chordal) mean is the
dominant eigenvector of the accumulated outer product (Markley et al., 2007):

$$\bar q = \arg\max_{\lVert q\rVert = 1}\ q^{\top} M\, q, \qquad M = \sum_{k=1}^{K} w_k\, q_k q_k^{\top}\ \in \mathbb{R}^{4\times4}$$

with geodesic distance on $SO(3)$

$$d(q_1, q_2) = 2\arccos\big|\langle q_1, q_2\rangle\big|.$$

**Why.** Rotations live on a curved manifold. The Euclidean mean of joint
*positions* falls **off** that manifold (it shrinks toward the interior), so
averaging positions folds fingers into shapes no hand can make. Averaging
orientations keeps every averaged frame a pose a real hand can hold.

---

## 4 · Palm-flip rejection — an angular-velocity prior

Single-camera depth is ambiguous, so the tracker sometimes flips a hand $180°$
between consecutive frames. Frames exceeding a physical angular-velocity ceiling
are treated as failed solves:

$$\omega_t = \frac{\Delta\theta_t}{\Delta t}, \qquad \Delta\theta_t = 2\arccos\big|\langle q_t, q_{t+1}\rangle\big|, \qquad \text{reject if } \omega_t > \omega_{\max}$$

with $\omega_{\max} = 900°/\text{s}$ (wrist), $700°/\text{s}$ (finger). Rejected
frames are re-filled by spherical linear interpolation between the nearest
trusted frames:

$$\mathrm{slerp}(q_0, q_1; t) = \frac{\sin\big((1-t)\,\Omega\big)}{\sin\Omega}\,q_0 + \frac{\sin\big(t\,\Omega\big)}{\sin\Omega}\,q_1, \qquad \Omega = \arccos\langle q_0, q_1\rangle$$

**Why.** No human wrist rotates near $1000°/\text{s}$; the flips are measurement
errors, not motion, so they are detected and interpolated over.

---

## 5 · Two-bone inverse kinematics — the law of cosines

The avatar's arms are longer than the signers', so copied joint angles misplace
the hands. The elbow is instead **solved**. With upper-arm length $a$, forearm
length $b$, and shoulder→wrist distance $c$, the interior elbow angle is:

$$c^2 = a^2 + b^2 - 2ab\cos\gamma \;\;\Longrightarrow\;\; \gamma = \arccos\!\left(\frac{a^2 + b^2 - c^2}{2ab}\right), \qquad c = \min\big(\lVert \text{shoulder} - \text{wrist}\rVert,\; a + b\big)$$

The elbow then lies on a circle about the shoulder–wrist axis; a **swivel angle**
$\phi$ selects the point matching the signer's observed bend.

**Why.** Fixing shoulder and wrist and solving the elbow puts each hand where it
belongs relative to its own shoulder, instead of at the end of a too-long limb.

---

## 6 · Hand clearance — one quadratic per collision

When two hands would intersect, their wrist targets are pushed apart along a unit
axis $u$ by the smallest $\delta$ that reaches a target separation $r$. Since
$\lVert u\rVert = 1$:

$$\lVert d + \delta u\rVert = r \;\;\Longrightarrow\;\; \delta^2 + 2(d\cdot u)\,\delta + \big(\lVert d\rVert^2 - r^2\big) = 0$$

$$\boxed{\;\delta = -(d\cdot u) + \sqrt{(d\cdot u)^2 - \lVert d\rVert^2 + r^2}\;}$$

**Why.** Exact and closed-form — no iteration. (The tempting shortcut of solving
each pair independently and taking the largest root is **not** exact: one pair's
push can drag an already-cleared pair back under. This was verified failing on
random point sets, which is why the pairs are resolved jointly.)

---

## 7 · Smoothing chosen on jerk

"Shaky" is **jerk** (the third time-derivative), not speed. Jerk is estimated by
a third finite difference:

$$\dddot{x}_t \approx x_{t+3} - 3x_{t+2} + 3x_{t+1} - x_t$$

The Gaussian smoothing width $\sigma$ (kernel $g(t) \propto e^{-t^2 / 2\sigma^2}$)
is chosen per sign as the **smallest** value satisfying an absolute ceiling:

$$\sigma^{*} = \min\Big\{\sigma : \max_t \lVert \dddot{x}_t(\sigma)\rVert \le J_{\max}\Big\}$$

**Why.** A relative bar lets an already-shaky clip stay shaky; an absolute jerk
ceiling forces a trembling sign to be damped before it ships, while leaving
genuinely smooth signs untouched.

---

## Complexity & footprint

| Stage | Cost |
|---|---|
| Pose extraction | one MediaPipe pass per frame |
| DTW (pairwise) | $O(nm)$ per pair |
| DBA per sign | $O(K \cdot nm \cdot \text{iters})$, iters ≤ 12 |
| IK + clearance | $O(1)$ closed-form per frame |

Runs entirely on **CPU**. Dataset: 17 signs, **329** screened takes (~18–21 per
sign) from ≥ 3 signers.

---

## Technical vocabulary (the terms to name explicitly)

Dynamic Time Warping · Fréchet / barycenter mean · Lloyd iteration · medoid
initialisation · 20 % trimmed mean (robust statistics) · rotation averaging on
$SO(3)$ · unit-quaternion (chordal vs geodesic) mean · SLERP · angular-velocity
prior · law-of-cosines / two-bone inverse kinematics · swivel angle · closed-form
quadratic constraint solve · finite-difference jerk · Gaussian kernel ·
silhouette-style split score.
