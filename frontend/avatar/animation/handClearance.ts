import * as THREE from 'three';

/**
 * Keep the avatar's two hands out of each other.
 *
 * armIK.ts puts each WRIST where the signer's was. That is the right target and
 * it is not enough, because a wrist is a point and a hand is not. Measured on
 * the shipped WE clip through the real retargeter: the wrists sit a correct
 * 13.3cm apart at their closest, and the HANDS close to 0.6cm between bone
 * centres and overlap on 23 frames of 59. This avatar's hand reaches 10.5cm
 * from the wrist while the sign brings the wrists to 7.1cm apart, so the
 * fingers of one hand end up inside the knuckles of the other. Measuring
 * wrist-to-wrist is what hid this the first time.
 *
 * The captured hands cannot answer the question either. MediaPipe's hand
 * landmarks arrive about 3.4x too small against the body — the recorded hand is
 * 0.077 hip→head units where this rig's is 0.262 — so the signers' fingers
 * clear each other by 1.8cm at a scale where the avatar's are deep inside each
 * other. Only the avatar's own geometry says what fits, which is why the
 * correction is made here at playback rather than in the clip.
 *
 * Two properties make it exact rather than iterative:
 *
 *   - a hand's world ORIENTATION is the captured direction and nothing else.
 *     The bone rotation is built in the parent's frame and multiplied back by
 *     it, so the forearm cancels: moving the elbow cannot turn the hand. Each
 *     hand therefore translates RIGIDLY with its wrist,
 *   - so for a push along a fixed axis, a pair of bones separated by `d` ends
 *     up |d + δu| apart. Requiring that to reach the clearance is one quadratic
 *     in δ per pair, and the answer is the largest root over all of them. No
 *     search, no re-pose to check.
 *
 * The axis is where this first went wrong, so it is worth stating what it is
 * not. Pushing along the WRIST-to-wrist direction is the obvious choice and it
 * barely works: measured on WE it clears 21 overlapping frames down to only 8,
 * because the wrists are separated sideways while the collision is almost
 * entirely in DEPTH. At the closest frames the pair direction runs [-0.06,
 * 0.12, -0.99] against a wrist axis of [0.86, -0.03, -0.50] — the hands are
 * stacked front to back, and sliding them apart sideways slides them past each
 * other instead. On one frame the dot product goes negative, so the sideways
 * push actively made that pair worse.
 *
 * That the collision is in depth is not a coincidence. Depth is the one axis a
 * single camera cannot measure: the wrists hold only 2cm of it through the
 * cross, which is less than a hand is thick. The frontal plane, where the
 * capture is trustworthy and where a viewer reads the sign, is left untouched.
 *
 * So the axis is the closest pair's own direction — but SMOOTHED, because the
 * closest pair jumps between bones from one frame to the next (measured going
 * from middle-tip/index-knuckle to little-tip/ring-knuckle in a single step)
 * and an axis that jumps makes the hands judder, which is the failure this
 * whole area of the code exists to remove. Its depth component is stable —
 * negative on every colliding frame of WE — while the sideways components are
 * what rattle, so smoothing settles it onto the depth separation the capture
 * lost and leaves δ varying smoothly enough to fade in and out.
 */

/** How fast the push axis follows the closest pair. Low enough to ride out the
 *  pair jumping between bones, high enough to track a hand that is moving. */
export const AXIS_FOLLOW = 0.25;

/**
 * Direction of the closest left/right pair, or null when nothing is close.
 *
 * Points from the right hand's bone toward the left's, so the sign is
 * consistent frame to frame and the smoothed axis cannot invert.
 */
export function closestPairAxis(
  left: readonly THREE.Vector3[],
  right: readonly THREE.Vector3[],
  within: number,
  out: THREE.Vector3,
): THREE.Vector3 | null {
  let best = within * within;
  let found = false;
  for (const a of left) {
    for (const b of right) {
      const dx = a.x - b.x;
      const dy = a.y - b.y;
      const dz = a.z - b.z;
      const dd = dx * dx + dy * dy + dz * dz;
      if (dd >= best || dd < 1e-12) continue;
      best = dd;
      out.set(dx, dy, dz);
      found = true;
    }
  }
  return found ? out.normalize() : null;
}

/**
 * Smallest symmetric push along `axis` that holds every left/right bone pair at
 * least `clearance` apart, capped at `cap`.
 *
 * `axis` must be unit and point from the right hand toward the left. The caller
 * moves the left wrist target by +δ/2 and the right by −δ/2.
 */
export function pushToClear(
  left: readonly THREE.Vector3[],
  right: readonly THREE.Vector3[],
  axis: THREE.Vector3,
  clearance: number,
  cap: number,
): number {
  // |d + δu|² = δ² + 2δ(d·u) + |d|², so a pair is TOO CLOSE exactly while δ
  // lies strictly between the roots of δ² + 2δ(d·u) + (|d|² − c²) = 0. Each pair
  // therefore forbids one open interval, and the answer is the smallest δ ≥ 0
  // outside all of them.
  //
  // Taking the largest per-pair root instead — the obvious reading, and what
  // this did first — is wrong: a pair already clear at δ = 0 can be dragged
  // back under the clearance by a push that some other pair demanded, when its
  // separation runs AGAINST the axis. Caught by the random-set test at 4.51cm
  // where 5cm was asked for, and invisible on the seventeen clips, which is
  // exactly why it was worth testing for.
  const c2 = clearance * clearance;
  let delta = 0;
  // Each pass either finishes or lifts δ onto some pair's upper root, and there
  // are finitely many of those, so this settles. The bound is a guard, not an
  // expected path; δ is capped below in any case.
  for (let pass = 0; pass < 8; pass++) {
    let moved = false;
    for (const a of left) {
      for (const b of right) {
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const dz = a.z - b.z;
        const du = dx * axis.x + dy * axis.y + dz * axis.z;
        const disc = du * du - (dx * dx + dy * dy + dz * dz) + c2;
        if (disc <= 0) continue; // this pair never closes to `clearance` along u
        const root = Math.sqrt(disc);
        const hi = root - du;
        if (delta >= hi) continue;
        if (delta <= -root - du) continue; // still below the interval: allowed
        delta = hi;
        moved = true;
        if (delta >= cap) return cap;
      }
    }
    if (!moved) break;
  }
  return delta < cap ? delta : cap;
}
