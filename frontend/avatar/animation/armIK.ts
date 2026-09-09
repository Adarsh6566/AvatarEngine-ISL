import * as THREE from 'three';

/**
 * Two-bone IK for the arms: put the avatar's HAND where the signer's hand was.
 *
 * Retargeting copies rotations, which is scale-invariant and therefore correct
 * for a body of any size — but only for angles. Position is not preserved, and
 * in sign language position is meaning: where a hand sits relative to the body,
 * and where the two hands sit relative to each other, is part of the sign.
 *
 * This avatar's arms are much longer than the signers' relative to its torso —
 * measured against hip→head, forearm 1.49x, whole arm 1.32x, on shoulders only
 * 1.06x wider. Copying the shoulder and elbow angles onto that frame swings the
 * hand out along a longer limb, so it lands somewhere the signer's never was.
 * On WE, where the arms cross in front of the chest, the signer's wrists close
 * to 0.119 (hip→head units) and the avatar's carried straight past each other
 * to 0.048 — the hands interpenetrating for 21 frames of 59.
 *
 * The fix is to stop treating the elbow as an input. The shoulder and the wrist
 * are the constraints; the elbow is solved for, so the wrist lands on target and
 * the arm bends however that requires:
 *
 *   - the target is the observed wrist, taken RELATIVE TO THE OBSERVED SHOULDER.
 *     Solving from the observed shoulder rather than the avatar's keeps this
 *     free of any question about how the model is oriented in the scene: only
 *     directions leave here, and each hand ends up in the same place relative to
 *     its own shoulder as the signer's was. The avatar's shoulders are 1.06x
 *     wider, so the gap between the hands comes out up to 0.029 LARGER than the
 *     signer's — the safe direction for a collision,
 *   - the elbow is placed by the cosine rule, on the circle of solutions,
 *   - the observed elbow chooses WHERE on that circle, so the arm still bends
 *     the way the signer's did rather than picking an arbitrary swivel.
 *
 * The caller feeds the solved elbow back in as if it had been captured, so the
 * existing swing extraction produces the bone rotations with no other change.
 *
 * Reach is not a concern in this direction — the avatar's arm is 0.932 against
 * the signer's 0.708, so every target the capture can produce is inside it —
 * but the clamp is kept because an unreachable target must degrade to a
 * straight arm rather than to NaN.
 */

/** Avatar arm geometry, in hip→head units so it compares with view space. */
export interface ArmRig {
  readonly upper: number;
  readonly fore: number;
}

export interface ArmRigs {
  readonly left: ArmRig;
  readonly right: ArmRig;
}

const _d = new THREE.Vector3();
const _h = new THREE.Vector3();
const _n = new THREE.Vector3();

/**
 * Elbow position that puts the wrist exactly on `target`.
 *
 * `hint` is the observed elbow, used only to choose the swivel around the
 * shoulder→wrist axis; its distance from the shoulder is ignored because that
 * is precisely the quantity that does not transfer between bodies.
 */
export function solveElbow(
  shoulder: THREE.Vector3,
  target: THREE.Vector3,
  hint: THREE.Vector3,
  upper: number,
  fore: number,
  out = new THREE.Vector3(),
): THREE.Vector3 {
  _d.copy(target).sub(shoulder);
  const reach = upper + fore;
  const dist = _d.length();
  if (dist < 1e-6) {
    // Degenerate: wrist on top of the shoulder. Any axis will do, but it has to
    // be a UNIT one — dividing the substitute by `dist` here scaled the axis by
    // a million and threw the elbow out of the scene.
    _n.set(0, -1, 0);
  } else {
    _n.copy(_d).divideScalar(dist);
  }
  // Just inside the limits, so the triangle never collapses to a NaN. Outside
  // them the arm cannot reach and folds or straightens as far as it goes; the
  // wrist then misses the target, which is the honest result.
  const clamped = Math.min(Math.max(dist, Math.abs(upper - fore) + 1e-5), reach - 1e-5);

  // Angle at the shoulder between the shoulder→wrist axis and the upper arm.
  const cos = (upper * upper + clamped * clamped - fore * fore) / (2 * upper * clamped);
  const angle = Math.acos(Math.min(1, Math.max(-1, cos)));

  // Swivel: the component of the observed elbow across the axis. If the
  // observed arm is dead straight there is no across-component to read, so any
  // perpendicular will do — the arm is straight either way.
  _h.copy(hint).sub(shoulder);
  _h.addScaledVector(_n, -_h.dot(_n));
  if (_h.lengthSq() < 1e-10) {
    _h.set(-_n.y, _n.x, 0);
    if (_h.lengthSq() < 1e-10) _h.set(0, -_n.z, _n.y);
  }
  _h.normalize();

  return out
    .copy(shoulder)
    .addScaledVector(_n, Math.cos(angle) * upper)
    .addScaledVector(_h, Math.sin(angle) * upper);
}

/**
 * Measure the avatar's arms from its rest pose, normalised by hip→head.
 *
 * Normalising here is what lets the solver take the captured wrist as a target
 * directly: the capture is scaled so hip→head is 1, so the same division puts
 * both bodies on one ruler. Returns null if the rig is missing a bone, and the
 * caller then keeps the rotation-only path.
 */
export function measureArms(
  worldPos: (bone: string) => THREE.Vector3 | null,
): ArmRigs | null {
  const hips = worldPos('hips');
  const head = worldPos('head');
  if (!hips || !head) return null;
  const span = head.distanceTo(hips);
  if (span < 1e-6) return null;

  const side = (prefix: 'left' | 'right'): ArmRig | null => {
    const s = worldPos(`${prefix}UpperArm`);
    const e = worldPos(`${prefix}LowerArm`);
    const w = worldPos(`${prefix}Hand`);
    if (!s || !e || !w) return null;
    return { upper: s.distanceTo(e) / span, fore: e.distanceTo(w) / span };
  };
  const left = side('left');
  const right = side('right');
  return left && right ? { left, right } : null;
}
