import { VRMHumanBoneName, type VRM } from '@pixiv/three-vrm';

/**
 * Collapse the avatar's legs so only the signing half of the body renders.
 *
 * ISL is signed between roughly the hips and above the head. The legs carry no
 * linguistic information, cost half the frame, and — once the camera is framed
 * waist-up — reappear underneath the floating input bar, which reads as a bug.
 *
 * They cannot simply be hidden. The model's geometry is grouped by MATERIAL,
 * not by body part: `Bottoms` (1,376 tris) and `Shoes` (524) are their own
 * primitives, but the bare skin of the legs lives inside `Body_00_SKIN`, a
 * single 9,532-triangle primitive that also contains the arms, hands, neck and
 * torso. Hiding that removes the hands, which are the entire point.
 *
 * So the legs are collapsed through the SKELETON instead. Scaling a bone scales
 * everything skinned to it and to its children, so shrinking the two upper-leg
 * bones pulls the whole chain — thighs, calves, feet, trousers and shoes alike,
 * since all of them are weighted to these joints — down to a point inside the
 * hips, where the torso hides it.
 *
 * Scale is used rather than a zero scale because an exact 0 produces a
 * degenerate matrix: normals become undefined and some drivers render a spray
 * of stretched triangles instead of nothing.
 *
 * This is applied to the RAW bone nodes. The normalized humanoid bones are
 * proxies whose transforms are rewritten from the normalized pose on every
 * humanoid.update(), so a scale written there is discarded on the next frame —
 * the raw hierarchy is what actually skins the mesh.
 *
 * Reversible: nothing is deleted, so restoring scale 1 brings the legs back.
 */
const LEG_ROOTS = [VRMHumanBoneName.LeftUpperLeg, VRMHumanBoneName.RightUpperLeg];

/** Small enough to vanish inside the hips, large enough to stay non-degenerate. */
const COLLAPSED = 0.001;

export function hideLegs(vrm: VRM, hidden = true): void {
  const scale = hidden ? COLLAPSED : 1;
  for (const bone of LEG_ROOTS) {
    // getRawBoneNode is the VRM 1.0 accessor; older rigs expose only the
    // normalized proxy, and scaling that is better than doing nothing.
    const node =
      vrm.humanoid.getRawBoneNode?.(bone) ?? vrm.humanoid.getNormalizedBoneNode(bone);
    node?.scale.setScalar(scale);
  }
}
