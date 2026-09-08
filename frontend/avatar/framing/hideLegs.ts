import * as THREE from 'three';
import type { VRM } from '@pixiv/three-vrm';

/**
 * Trim the avatar below the waist, so only the signing half of the body exists.
 *
 * ISL is signed between roughly the hips and above the head. The legs carry no
 * linguistic information, cost half the frame, and — once the camera is framed
 * waist-up — reappear underneath the floating input bar, which reads as a bug.
 *
 * WHY THE GEOMETRY IS EDITED RATHER THAN HIDDEN
 * ---------------------------------------------
 * Two simpler approaches were tried first and both failed, for reasons worth
 * keeping so they are not retried:
 *
 * 1. Hiding the leg meshes. Impossible: the model is grouped by MATERIAL, not
 *    by body part. `Bottoms` and `Shoes` are their own primitives, but the bare
 *    skin of the legs lives inside `Body_00_SKIN` — a single 9,532-triangle
 *    primitive that also holds the arms, hands, neck and torso. Hiding it takes
 *    the hands with it, and the hands are the entire point.
 *
 * 2. Collapsing the leg BONES, then clipping away what remained. Scaling
 *    leftUpperLeg/rightUpperLeg does shrink the legs, but geometry is weighted
 *    per joint and `hips` is its own skin joint — the pelvis, the crotch of the
 *    body mesh and the trouser waistband are weighted there and survived
 *    untouched, leaving a stump under the jacket. `hips` cannot be scaled away
 *    in turn, because the whole skeleton descends from it. Adding a clipping
 *    plane to remove the stump then broke something worse: clipping tests the
 *    ANIMATED world position, so the arms were erased the moment the hands
 *    dropped toward the hips — which in sign language is constantly.
 *
 * So the triangles are removed instead, tested against the BIND POSE. A
 * vertex's bind position does not change when the avatar moves, so nothing that
 * is kept can later be cut: the hands may travel wherever the sign takes them
 * and stay whole. It is also cheaper than either alternative, since the removed
 * triangles are never submitted to the GPU at all.
 *
 * Nothing is written to disk; this edits the loaded geometry in memory, so
 * reloading the model restores the legs.
 */

/**
 * Bind-pose height below which geometry is dropped, in the model's own units
 * (before the +0.2 lift each pipeline applies when adding the scene).
 *
 * From this rig: hips sit at 1.027, the upper-leg joints at 0.983. The cut goes
 * just above the hips joint so the pelvis goes with the legs, taking a little
 * jacket hem with it — which is below the framed area anyway.
 */
const WAIST_Y = 1.05;

/**
 * Drop every triangle lying entirely below WAIST_Y in the bind pose.
 *
 * Only triangles with ALL THREE vertices below the line go. Dropping any
 * triangle that merely crosses it would erode a ragged edge up into the torso;
 * keeping the straddlers leaves a slightly uneven hem that the jacket hides.
 */
function trimBelowWaist(mesh: THREE.Mesh): void {
  const geometry = mesh.geometry;
  const position = geometry.getAttribute('position');
  if (!position) return;

  const below = (i: number) => position.getY(i) < WAIST_Y;
  const kept: number[] = [];

  if (geometry.index) {
    const index = geometry.index;
    for (let t = 0; t < index.count; t += 3) {
      const a = index.getX(t);
      const b = index.getX(t + 1);
      const c = index.getX(t + 2);
      if (below(a) && below(b) && below(c)) continue;
      kept.push(a, b, c);
    }
    if (kept.length === index.count) return; // nothing below the waist
    geometry.setIndex(kept);
  } else {
    // Non-indexed: build an index selecting the triangles worth keeping, rather
    // than rewriting the much larger position buffer.
    for (let v = 0; v < position.count; v += 3) {
      if (below(v) && below(v + 1) && below(v + 2)) continue;
      kept.push(v, v + 1, v + 2);
    }
    if (kept.length === position.count) return;
    geometry.setIndex(kept);
  }

  // The bounding volumes still describe a whole body. A stale bounding sphere
  // makes frustum culling drop the mesh entirely at some camera angles.
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
}

export function hideLegs(vrm: VRM): void {
  vrm.scene.traverse((object) => {
    const mesh = object as THREE.Mesh;
    if (mesh.isMesh && mesh.geometry) trimBelowWaist(mesh);
  });
}
