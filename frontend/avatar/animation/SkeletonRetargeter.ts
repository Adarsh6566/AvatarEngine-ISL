import * as THREE from 'three';
import { VRMHumanBoneName, type VRM } from '@pixiv/three-vrm';

/**
 * SkeletonRetargeter — turns captured joint POSITIONS into VRM bone ROTATIONS.
 *
 * Extracted verbatim from VrmRenderer so the viewer and the app share ONE
 * implementation and cannot drift. It owns no VRM, adds no lights, reads no URL
 * parameters, and touches no scene: give it a VRM to measure and a frame of
 * joints, and it writes a normalized pose. Callers own everything else.
 *
 * Method — forward-kinematic SWING extraction (unchanged):
 *
 *   restDir  = normalize(childRestPos - boneRestPos)      (VRM normalized T-pose)
 *   obsDir   = normalize(childObsPos  - boneObsPos)       (stream, view space)
 *   qLocal   = fromUnitVectors(restDir, Rparent⁻¹ · obsDir)   (local swing)
 *   Rworld   = Rparent · qLocal                           (walk parents→children)
 *
 * Applied via vrm.humanoid.setNormalizedPose (identity = rest), the same
 * supported path AvatarController uses; the raw rig is never touched. Swing
 * only — twist about a bone's own axis is not recoverable this way.
 *
 * IMPORTANT: captureRest() must be called while the VRM is in its T-pose. Any
 * pose applied first (e.g. AvatarController.applyNaturalPose, which rotates the
 * upper arms ~80° down) is baked into the rest directions and corrupts every
 * arm, hand and finger rotation derived from them.
 */

const V = VRMHumanBoneName;

/** One driven bone: which VRM bone, its nearest DRIVEN ancestor (frame parent),
 *  the VRM child used for the rest direction, and the stream joints giving the
 *  observed direction. Order matters: parents precede children. */
export interface Drive {
  bone: VRMHumanBoneName;
  parent: VRMHumanBoneName;
  restChild: VRMHumanBoneName;
  from: string;
  to: string;
  /** Tip bones (finger/thumb distal) have no child bone to read a rest direction
   *  from; at rest the finger is straight, so use the parent bone's axis instead. */
  restFromParent?: boolean;
}

function sideDrives(Side: 'Left' | 'Right', p: 'l' | 'r'): Drive[] {
  const B = (n: string) => V[`${Side}${n}` as keyof typeof V] as VRMHumanBoneName;
  return [
    { bone: B('UpperArm'), parent: V.Chest, restChild: B('LowerArm'), from: `${p}Shoulder`, to: `${p}Elbow` },
    { bone: B('LowerArm'), parent: B('UpperArm'), restChild: B('Hand'), from: `${p}Elbow`, to: `${p}Wrist` },
    // Hand (wrist) orientation: driven by the palm→middle-knuckle direction, which
    // MATCHES its rest (Hand→MiddleProximal). Using Wrist→Hand instead twists the
    // hand by the noisy gap between the body wrist and MediaPipe's hand root, and
    // every finger hangs off this bone, so that error cascades into all of them.
    { bone: B('Hand'), parent: B('LowerArm'), restChild: B('MiddleProximal'), from: `${p}Hand`, to: `${p}Middle1` },
    // Fingers: 4 captured joints → all three bones driven (proximal 1→2,
    // intermediate 2→3, distal 3→4), so the hand can fully close. Thumb has 3
    // landmarks → proximal (1→2) + distal (2→3).
    // Thumb: proximal only. Its VRM rest pose is angled (not straight like the
    // fingers), so the straight-digit tip-rest assumption flips the distal swing
    // ("correct motion, opposite direction"). Proximal alone curls it correctly.
    { bone: B('ThumbProximal'), parent: B('Hand'), restChild: B('ThumbDistal'), from: `${p}Thumb1`, to: `${p}Thumb2` },
    { bone: B('IndexProximal'), parent: B('Hand'), restChild: B('IndexIntermediate'), from: `${p}Index1`, to: `${p}Index2` },
    { bone: B('IndexIntermediate'), parent: B('IndexProximal'), restChild: B('IndexDistal'), from: `${p}Index2`, to: `${p}Index3` },
    { bone: B('IndexDistal'), parent: B('IndexIntermediate'), restChild: B('IndexDistal'), from: `${p}Index3`, to: `${p}Index4`, restFromParent: true },
    { bone: B('MiddleProximal'), parent: B('Hand'), restChild: B('MiddleIntermediate'), from: `${p}Middle1`, to: `${p}Middle2` },
    { bone: B('MiddleIntermediate'), parent: B('MiddleProximal'), restChild: B('MiddleDistal'), from: `${p}Middle2`, to: `${p}Middle3` },
    { bone: B('MiddleDistal'), parent: B('MiddleIntermediate'), restChild: B('MiddleDistal'), from: `${p}Middle3`, to: `${p}Middle4`, restFromParent: true },
    { bone: B('RingProximal'), parent: B('Hand'), restChild: B('RingIntermediate'), from: `${p}Ring1`, to: `${p}Ring2` },
    { bone: B('RingIntermediate'), parent: B('RingProximal'), restChild: B('RingDistal'), from: `${p}Ring2`, to: `${p}Ring3` },
    { bone: B('RingDistal'), parent: B('RingIntermediate'), restChild: B('RingDistal'), from: `${p}Ring3`, to: `${p}Ring4`, restFromParent: true },
    { bone: B('LittleProximal'), parent: B('Hand'), restChild: B('LittleIntermediate'), from: `${p}Pinky1`, to: `${p}Pinky2` },
    { bone: B('LittleIntermediate'), parent: B('LittleProximal'), restChild: B('LittleDistal'), from: `${p}Pinky2`, to: `${p}Pinky3` },
    { bone: B('LittleDistal'), parent: B('LittleIntermediate'), restChild: B('LittleDistal'), from: `${p}Pinky3`, to: `${p}Pinky4`, restFromParent: true },
    { bone: B('UpperLeg'), parent: V.Hips, restChild: B('LowerLeg'), from: `${p}Hip`, to: `${p}Knee` },
    { bone: B('LowerLeg'), parent: B('UpperLeg'), restChild: B('Foot'), from: `${p}Knee`, to: `${p}Ankle` },
  ];
}

export const DRIVES: Drive[] = [
  { bone: V.Spine, parent: V.Hips, restChild: V.Chest, from: 'spine', to: 'chest' },
  { bone: V.Chest, parent: V.Spine, restChild: V.Neck, from: 'chest', to: 'neck' },
  { bone: V.Neck, parent: V.Chest, restChild: V.Head, from: 'neck', to: 'head' },
  ...sideDrives('Left', 'l'),
  ...sideDrives('Right', 'r'),
];

/** Lower-body bones, skipped unless driveLegs. */
const LEG_BONES: ReadonlySet<VRMHumanBoneName> = new Set([
  V.LeftUpperLeg, V.LeftLowerLeg, V.RightUpperLeg, V.RightLowerLeg,
]);

/** Torso + head bones, skipped unless driveBody — kept upright/still for signing. */
const TORSO_BONES: ReadonlySet<VRMHumanBoneName> = new Set([
  V.Spine, V.Chest, V.Neck,
]);

/** Non-proximal finger bones (intermediate + distal), skipped when fingerMode is
 *  'prox' so only the base knuckle is driven. */
const FINGER_NONPROXIMAL: ReadonlySet<VRMHumanBoneName> = new Set([
  V.LeftThumbDistal, V.LeftIndexIntermediate, V.LeftIndexDistal, V.LeftMiddleIntermediate, V.LeftMiddleDistal,
  V.LeftRingIntermediate, V.LeftRingDistal, V.LeftLittleIntermediate, V.LeftLittleDistal,
  V.RightThumbDistal, V.RightIndexIntermediate, V.RightIndexDistal, V.RightMiddleIntermediate, V.RightMiddleDistal,
  V.RightRingIntermediate, V.RightRingDistal, V.RightLittleIntermediate, V.RightLittleDistal,
]);

/** All driven finger bones, skipped when fingerMode is 'off'. */
const FINGER_BONES: ReadonlySet<VRMHumanBoneName> = new Set([
  V.LeftThumbProximal, V.LeftThumbDistal, V.LeftIndexProximal, V.LeftMiddleProximal, V.LeftRingProximal, V.LeftLittleProximal,
  V.LeftIndexIntermediate, V.LeftIndexDistal, V.LeftMiddleIntermediate, V.LeftMiddleDistal,
  V.LeftRingIntermediate, V.LeftRingDistal, V.LeftLittleIntermediate, V.LeftLittleDistal,
  V.RightThumbProximal, V.RightThumbDistal, V.RightIndexProximal, V.RightMiddleProximal, V.RightRingProximal, V.RightLittleProximal,
  V.RightIndexIntermediate, V.RightIndexDistal, V.RightMiddleIntermediate, V.RightMiddleDistal,
  V.RightRingIntermediate, V.RightRingDistal, V.RightLittleIntermediate, V.RightLittleDistal,
]);

/** Joints for one frame, as carried by SkeletonStreamFrame. Structural so this
 *  module does not depend on the skeleton module (direction stays avatar ← skeleton). */
export type RetargetJoints = Readonly<Record<string, readonly [number, number, number, number] | null>>;

/**
 * Retargeting knobs. Defaults are the sign-language configuration: body upright,
 * legs still, fingers fully driven, no axis remapping. VrmRenderer overrides
 * these from its URL debug parameters; the app uses the defaults.
 */
export interface RetargetOptions {
  /** Negate an input axis (±1). */
  sx: number;
  sy: number;
  sz: number;
  /** Swap two input axes: 'xz' | 'xy' | 'yz' | ''. */
  swap: string;
  /** Force the hips frame to identity instead of deriving it from the torso. */
  rootIdentity: boolean;
  driveLegs: boolean;
  driveBody: boolean;
  fingerMode: 'full' | 'prox' | 'off';
  /**
   * Temporal damping for FINGER rotations only, 0 (off) to <1.
   *
   * Finger depth is the least reliable channel in a monocular capture: a
   * bone's observed segment can collapse toward zero length between frames
   * (measured 0.0080 -> 0.0366 view units on one index proximal), and since
   * the segment is normalised to get a direction, a short segment turns
   * noise into a large swing. Slerping each finger rotation toward the
   * previous frame's damps that without dropping bones, so the hand keeps
   * its articulation. Arms and torso are left alone — their segments are
   * long enough that direction is stable.
   */
  fingerSmoothing: number;
}

export const DEFAULT_RETARGET_OPTIONS: RetargetOptions = {
  sx: 1,
  sy: 1,
  sz: 1,
  swap: '',
  rootIdentity: true,
  driveLegs: false,
  driveBody: false,
  fingerMode: 'full',
  fingerSmoothing: 0,
};

const _c = new THREE.Vector3();

export class SkeletonRetargeter {
  private readonly options: RetargetOptions;

  /** Rest bone directions (normalized), captured from the VRM T-pose. */
  private readonly restDir = new Map<VRMHumanBoneName, THREE.Vector3>();
  private readonly rootParentWorldQ = new THREE.Quaternion();
  private captured = false;

  /** Previous frame's local rotation per damped bone, for fingerSmoothing. */
  private readonly prevLocal = new Map<VRMHumanBoneName, THREE.Quaternion>();

  constructor(options: Partial<RetargetOptions> = {}) {
    this.options = { ...DEFAULT_RETARGET_OPTIONS, ...options };
  }

  /**
   * Forget the smoothing history.
   *
   * Call when starting a new clip: otherwise the first frames are dragged
   * toward the last pose of the previous one.
   */
  reset(): void {
    this.prevLocal.clear();
  }

  /** True once captureRest() has measured a VRM. applyPose is a no-op before then. */
  get hasRest(): boolean {
    return this.captured;
  }

  /**
   * Record each driven bone's rest direction from the normalized T-pose.
   *
   * Must run before any pose is applied to the VRM — see the class docstring.
   */
  captureRest(vrm: VRM): void {
    const node = (b: VRMHumanBoneName) => vrm.humanoid.getNormalizedBoneNode(b);
    const worldPos = (b: VRMHumanBoneName): THREE.Vector3 | null => {
      const n = node(b);
      if (!n) return null;
      n.updateWorldMatrix(true, false);
      return n.getWorldPosition(new THREE.Vector3());
    };
    this.restDir.clear();
    for (const d of DRIVES) {
      if (d.restFromParent) {
        // Tip bone: no child node. At rest the finger is straight, so the tip's
        // axis equals its parent bone's axis (parent-node → this-node direction).
        const self = worldPos(d.bone);
        const par = worldPos(d.parent);
        if (self && par && self.distanceToSquared(par) > 1e-8) {
          this.restDir.set(d.bone, self.clone().sub(par).normalize());
        }
        continue;
      }
      const a = worldPos(d.bone);
      const b = worldPos(d.restChild);
      if (a && b) this.restDir.set(d.bone, b.clone().sub(a).normalize());
    }
    const hipsNode = node(V.Hips);
    hipsNode?.parent?.getWorldQuaternion(this.rootParentWorldQ);
    this.captured = true;
  }

  /**
   * Compute and apply the pose for one frame of joints.
   *
   * No-op until captureRest() has run, so a caller may push frames before the
   * VRM is ready without special-casing.
   */
  applyPose(vrm: VRM, joints: RetargetJoints): void {
    if (!this.captured) return;
    const o = this.options;

    const pos = (name: string): THREE.Vector3 | null => {
      const v = joints[name];
      if (!v) return null;
      let x = v[0] * o.sx;
      let y = v[1] * o.sy;
      let z = v[2] * o.sz;
      if (o.swap === 'xz') [x, z] = [z, x];
      else if (o.swap === 'xy') [x, y] = [y, x];
      else if (o.swap === 'yz') [y, z] = [z, y];
      return new THREE.Vector3(x, y, z);
    };

    const pose: Partial<Record<VRMHumanBoneName, { rotation: [number, number, number, number] }>> = {};
    const Rworld = new Map<VRMHumanBoneName, THREE.Quaternion>();
    const identity = new THREE.Quaternion();

    // Root (hips): anatomical frame from the observed torso.
    const hips = pos('hips');
    const chest = pos('chest');
    const lSh = pos('lShoulder');
    const rSh = pos('rShoulder');
    const Rhips = new THREE.Quaternion();
    if (!o.rootIdentity && hips && chest && lSh && rSh) {
      const up = chest.clone().sub(hips).normalize();
      const lr = rSh.clone().sub(lSh).normalize();
      // forward = up × (L→R): for a camera-facing signer this is +Z, so the
      // torso frame is ~identity and the loader's rotateVRM0 alone orients the
      // avatar toward the viewer. (cross(lr, up) would add a spurious 180°-about-Y,
      // cancelling rotateVRM0 → avatar faces away, limbs inherit the flip.)
      const f = new THREE.Vector3().crossVectors(up, lr).normalize();
      const r = new THREE.Vector3().crossVectors(up, f).normalize();
      Rhips.setFromRotationMatrix(new THREE.Matrix4().makeBasis(r, up, f));
    }
    Rworld.set(V.Hips, Rhips);
    const hipsLocal = this.rootParentWorldQ.clone().invert().multiply(Rhips);
    pose[V.Hips] = { rotation: [hipsLocal.x, hipsLocal.y, hipsLocal.z, hipsLocal.w] };

    for (const d of DRIVES) {
      const Rparent = Rworld.get(d.parent) ?? identity;
      if (
        (!o.driveLegs && LEG_BONES.has(d.bone)) ||
        (!o.driveBody && TORSO_BONES.has(d.bone))
      ) {
        Rworld.set(d.bone, Rparent); // leg/torso left at rest (upright, still)
        continue;
      }
      const fm = o.fingerMode;
      if (
        (fm === 'off' && FINGER_BONES.has(d.bone)) ||
        (fm === 'prox' && FINGER_NONPROXIMAL.has(d.bone))
      ) {
        Rworld.set(d.bone, Rparent); // finger bone left at rest
        continue;
      }
      const rest = this.restDir.get(d.bone);
      const a = pos(d.from);
      const b = pos(d.to);
      if (!rest || !a || !b) {
        Rworld.set(d.bone, Rparent); // undriven this frame: inherit parent frame, stay at rest
        continue;
      }
      _c.copy(b).sub(a);
      if (_c.lengthSq() < 1e-8) {
        Rworld.set(d.bone, Rparent);
        continue;
      }
      const obsLocal = _c.clone().applyQuaternion(Rparent.clone().invert()).normalize();
      let qLocal = new THREE.Quaternion().setFromUnitVectors(rest, obsLocal);

      // Damp finger jitter by blending with the previous frame's rotation.
      if (o.fingerSmoothing > 0 && FINGER_BONES.has(d.bone)) {
        const previous = this.prevLocal.get(d.bone);
        if (previous) qLocal = previous.clone().slerp(qLocal, 1 - o.fingerSmoothing);
        this.prevLocal.set(d.bone, qLocal.clone());
      }

      pose[d.bone] = { rotation: [qLocal.x, qLocal.y, qLocal.z, qLocal.w] };
      Rworld.set(d.bone, Rparent.clone().multiply(qLocal));
    }

    vrm.humanoid.setNormalizedPose(pose);
    vrm.humanoid.update();
  }
}
