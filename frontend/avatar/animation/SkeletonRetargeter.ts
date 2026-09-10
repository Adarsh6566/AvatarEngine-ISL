import * as THREE from 'three';
import { measureArms, solveElbow, type ArmRigs } from './armIK';
import { AXIS_FOLLOW, closestPairAxis, pushToClear } from './handClearance';
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
  /**
   * A second axis across the bone, making its orientation fully determined.
   *
   * One direction fixes where a bone points but leaves it free to roll about
   * that direction, and for the hand that free roll IS the palm's facing. A
   * second, non-parallel axis across the knuckles pins it, so the palm faces
   * where the signer's did rather than wherever rest happened to leave it.
   *
   * Only the hand declares this. Fingers are single-axis by nature, and the
   * arm's roll is not observable from joint positions alone.
   */
  acrossFrom?: string;
  acrossTo?: string;
  restAcrossFrom?: VRMHumanBoneName;
  restAcrossTo?: VRMHumanBoneName;
}

/**
 * Rotation carrying one (primary, secondary) axis pair onto another.
 *
 * Both pairs are orthonormalised the same way — primary kept exact, secondary
 * only used to place the plane — so the result points the bone along `primary`
 * and rolls it so `secondary` lands as close as the primary allows. Returns
 * null when either pair is degenerate (parallel or zero-length), leaving the
 * caller to fall back to the swing.
 */
function orientationBetween(
  restPrimary: THREE.Vector3,
  restSecondary: THREE.Vector3,
  obsPrimary: THREE.Vector3,
  obsSecondary: THREE.Vector3,
): THREE.Quaternion | null {
  const basis = (primary: THREE.Vector3, secondary: THREE.Vector3): THREE.Quaternion | null => {
    const x = primary.clone().normalize();
    const z = new THREE.Vector3().crossVectors(x, secondary);
    if (z.lengthSq() < 1e-10) return null; // secondary parallel to primary: no plane
    z.normalize();
    const y = new THREE.Vector3().crossVectors(z, x).normalize();
    return new THREE.Quaternion().setFromRotationMatrix(
      new THREE.Matrix4().makeBasis(x, y, z),
    );
  };
  const qRest = basis(restPrimary, restSecondary);
  const qObs = basis(obsPrimary, obsSecondary);
  if (!qRest || !qObs) return null;
  return qObs.multiply(qRest.invert());
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
    // The across-knuckles axis is what makes the palm face the right way; see
    // Drive.acrossFrom. Index→Little spans the knuckle fan, so it is the widest
    // and least noise-sensitive baseline available across the palm.
    {
      bone: B('Hand'),
      parent: B('LowerArm'),
      restChild: B('MiddleProximal'),
      from: `${p}Hand`,
      to: `${p}Middle1`,
      acrossFrom: `${p}Index1`,
      acrossTo: `${p}Pinky1`,
      restAcrossFrom: B('IndexProximal'),
      restAcrossTo: B('LittleProximal'),
    },
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

/** Each driven bone's parent, for walking rest offsets back to the hips. */
const PARENT_OF: ReadonlyMap<VRMHumanBoneName, VRMHumanBoneName> = new Map(
  DRIVES.map((d) => [d.bone, d.parent] as const),
);

/** Shoulder→hand, in chain order. Rebuilt when hand clearance moves a wrist. */
const ARM_CHAIN: Readonly<Record<'l' | 'r', readonly Drive[]>> = {
  l: DRIVES.filter((d) => d.bone === V.LeftUpperArm || d.bone === V.LeftLowerArm || d.bone === V.LeftHand),
  r: DRIVES.filter((d) => d.bone === V.RightUpperArm || d.bone === V.RightLowerArm || d.bone === V.RightHand),
};

/** Every bone of one hand, as collision points. Distals also contribute a tip. */
const HAND_POINTS: Readonly<Record<'l' | 'r', readonly VRMHumanBoneName[]>> = {
  l: [
    V.LeftHand,
    V.LeftThumbProximal, V.LeftThumbDistal,
    V.LeftIndexProximal, V.LeftIndexIntermediate, V.LeftIndexDistal,
    V.LeftMiddleProximal, V.LeftMiddleIntermediate, V.LeftMiddleDistal,
    V.LeftRingProximal, V.LeftRingIntermediate, V.LeftRingDistal,
    V.LeftLittleProximal, V.LeftLittleIntermediate, V.LeftLittleDistal,
  ],
  r: [
    V.RightHand,
    V.RightThumbProximal, V.RightThumbDistal,
    V.RightIndexProximal, V.RightIndexIntermediate, V.RightIndexDistal,
    V.RightMiddleProximal, V.RightMiddleIntermediate, V.RightMiddleDistal,
    V.RightRingProximal, V.RightRingIntermediate, V.RightRingDistal,
    V.RightLittleProximal, V.RightLittleIntermediate, V.RightLittleDistal,
  ],
};

/** Fingertips are not bones; extend each distal by its own length to reach one. */
const DISTAL_TIPS: ReadonlySet<VRMHumanBoneName> = new Set([
  V.LeftThumbDistal, V.LeftIndexDistal, V.LeftMiddleDistal, V.LeftRingDistal, V.LeftLittleDistal,
  V.RightThumbDistal, V.RightIndexDistal, V.RightMiddleDistal, V.RightRingDistal, V.RightLittleDistal,
]);

/** Knuckle pairs used to size the auto clearance from the rig's own hand. */
const KNUCKLE_PITCH: readonly (readonly [VRMHumanBoneName, VRMHumanBoneName])[] = [
  [V.LeftIndexProximal, V.LeftMiddleProximal],
  [V.LeftMiddleProximal, V.LeftRingProximal],
  [V.LeftRingProximal, V.LeftLittleProximal],
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
  /**
   * Solve the elbow so the HAND lands where the signer's did, instead of
   * copying the elbow angle onto a longer arm. See armIK.ts. Off falls back to
   * pure rotation transfer, which is what shipped before and is kept as an
   * escape hatch for comparing the two.
   */
  armIK: boolean;
  /**
   * Least distance allowed between the two hands' bones, in hip→head units.
   * Reached by pushing the wrist targets apart; see handClearance.ts.
   *
   * 'auto' measures it from THIS rig — 1.35x the mean gap between adjacent
   * knuckles, which is a finger's width plus enough for the palm behind it, so
   * a differently proportioned avatar gets its own number rather than one tuned
   * to this model. 0 disables the pass. Requires armIK, which is what makes the
   * wrist a target that can be moved.
   */
  handClearance: number | 'auto';
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
  armIK: true,
  handClearance: 'auto',
};

/** Ceiling on the hand-clearance push, in hip→head units (4.8cm on this rig).
 *  A safety limit, not an operating point: the worst of the seventeen signs
 *  asks for 4.1cm. A sign that genuinely holds the hands together should end up
 *  looking crowded rather than pulled apart, so the pass stops here instead of
 *  reshaping the gesture to satisfy the geometry. */
const MAX_CLEARANCE_PUSH = 0.09;

const _c = new THREE.Vector3();
const _ikL = new THREE.Vector3();
const _ikR = new THREE.Vector3();
const _axis = new THREE.Vector3();
const _shift = new THREE.Vector3();

export class SkeletonRetargeter {
  private readonly options: RetargetOptions;

  /** Avatar arm lengths in hip->head units, for armIK. Null if the rig lacks arms. */
  private armRigs: ArmRigs | null = null;
  /** Rest bone directions (normalized), captured from the VRM T-pose. */
  private readonly restDir = new Map<VRMHumanBoneName, THREE.Vector3>();
  /** Rest offset from each driven bone's PARENT, for forward kinematics. */
  private readonly restLocal = new Map<VRMHumanBoneName, THREE.Vector3>();
  /** Resolved hand clearance in hip->head units; 0 when the pass is off. */
  private clearance = 0;
  /** Smoothed direction the hands are being pushed apart along, while in contact. */
  private pushAxis: THREE.Vector3 | null = null;
  /** Rest across-axis, for the bones that declare one (the hands). */
  private readonly restAcross = new Map<VRMHumanBoneName, THREE.Vector3>();
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
    this.pushAxis = null;
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
    this.restAcross.clear();
    for (const d of DRIVES) {
      if (d.restAcrossFrom && d.restAcrossTo) {
        const from = worldPos(d.restAcrossFrom);
        const to = worldPos(d.restAcrossTo);
        if (from && to && from.distanceToSquared(to) > 1e-8) {
          this.restAcross.set(d.bone, to.clone().sub(from).normalize());
        }
      }
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
    // Rest offsets for the FK used by the hand-clearance pass. Taken from the
    // bone's DRIVE parent rather than its rig parent: anything between them
    // (a shoulder, an upper chest) is never driven, so it stays at rest and its
    // contribution is already inside this constant offset.
    //
    // Divided by hip→head, so the FK lands in the SAME units as the capture and
    // as the clearance. Leaving them in the rig's metres silently delivered only
    // `span` of every push — 53% on this avatar — and the clearance pass stalled
    // four frames short no matter how far its cap was raised.
    const span = this.restSpan(worldPos);
    this.restLocal.clear();
    for (const d of DRIVES) {
      const self = worldPos(d.bone);
      const par = worldPos(d.parent);
      if (self && par) this.restLocal.set(d.bone, self.clone().sub(par).divideScalar(span));
    }

    this.armRigs = measureArms((b) => worldPos(b as VRMHumanBoneName));
    this.clearance = this.resolveClearance(worldPos, span);
    const hipsNode = node(V.Hips);
    hipsNode?.parent?.getWorldQuaternion(this.rootParentWorldQ);
    this.captured = true;
  }

  /**
   * Hand clearance in hip→head units, measured from this rig when set to 'auto'.
   *
   * The knuckle pitch is the only number on the model that says how thick its
   * fingers are, and 1.35x it leaves a finger's width plus a little for the palm
   * behind — 2.5cm on this avatar, against knuckles 1.8cm apart.
   */
  private restSpan(worldPos: (b: VRMHumanBoneName) => THREE.Vector3 | null): number {
    const hips = worldPos(V.Hips);
    const head = worldPos(V.Head);
    const span = hips && head ? head.distanceTo(hips) : 0;
    return span > 1e-6 ? span : 1;
  }

  private resolveClearance(
    worldPos: (b: VRMHumanBoneName) => THREE.Vector3 | null,
    span: number,
  ): number {
    const asked = this.options.handClearance;
    if (asked !== 'auto') return Math.max(0, asked);
    let total = 0;
    let n = 0;
    for (const [a, b] of KNUCKLE_PITCH) {
      const pa = worldPos(a);
      const pb = worldPos(b);
      if (pa && pb) { total += pa.distanceTo(pb) / span; n++; }
    }
    return n > 0 ? (total / n) * 1.35 : 0;
  }

  /**
   * One bone's local rotation, or null when this frame cannot drive it.
   *
   * Split out because the hand-clearance pass rebuilds the three arm bones a
   * second time against moved wrist targets, and must do it by exactly the same
   * arithmetic. Smoothing deliberately stays with the caller: running it twice
   * on one frame would advance the finger history twice.
   */
  private boneRotation(
    d: Drive,
    Rparent: THREE.Quaternion,
    pos: (name: string) => THREE.Vector3 | null,
  ): THREE.Quaternion | null {
    const rest = this.restDir.get(d.bone);
    const a = pos(d.from);
    const b = pos(d.to);
    if (!rest || !a || !b) return null;
    _c.copy(b).sub(a);
    if (_c.lengthSq() < 1e-8) return null;

    const inv = Rparent.clone().invert();
    const obsLocal = _c.clone().applyQuaternion(inv).normalize();
    let qLocal = new THREE.Quaternion().setFromUnitVectors(rest, obsLocal);

    // Hand: recover roll too, so the palm faces where the signer's did. The
    // swing above is the fallback when the knuckles are missing or collapse
    // onto the middle axis (a fist seen end-on), where no plane is defined.
    const restAcross = this.restAcross.get(d.bone);
    const acrossA = d.acrossFrom ? pos(d.acrossFrom) : null;
    const acrossB = d.acrossTo ? pos(d.acrossTo) : null;
    if (restAcross && acrossA && acrossB) {
      const obsAcrossLocal = acrossB.clone().sub(acrossA).applyQuaternion(inv);
      const full = orientationBetween(rest, restAcross, obsLocal, obsAcrossLocal);
      if (full) qLocal = full;
    }
    return qLocal;
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

    const captured = (name: string): THREE.Vector3 | null => {
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

    // Replace the captured elbow with one that puts the wrist on target for
    // THIS rig's arm lengths. Everything downstream still reads positions and
    // extracts swings from them, so the two arm drives pick the corrected
    // angles up without knowing IK happened. The wrist and everything past it
    // — hand, fingers — is left exactly as captured.
    let ikL: THREE.Vector3 | null = null;
    let ikR: THREE.Vector3 | null = null;
    if (o.armIK && this.armRigs) {
      const solve = (p: 'l' | 'r', rig: { upper: number; fore: number }, out: THREE.Vector3) => {
        const s = captured(`${p}Shoulder`);
        const e = captured(`${p}Elbow`);
        const w = captured(`${p}Wrist`);
        return s && e && w ? solveElbow(s, w, e, rig.upper, rig.fore, out) : null;
      };
      ikL = solve('l', this.armRigs.left, _ikL);
      ikR = solve('r', this.armRigs.right, _ikR);
    }
    const pos = (name: string): THREE.Vector3 | null => {
      if (name === 'lElbow' && ikL) return ikL;
      if (name === 'rElbow' && ikR) return ikR;
      return captured(name);
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
      let qLocal = this.boneRotation(d, Rparent, pos);
      if (!qLocal) {
        Rworld.set(d.bone, Rparent); // undriven this frame: inherit parent frame, stay at rest
        continue;
      }

      // Damp finger jitter by blending with the previous frame's rotation.
      if (o.fingerSmoothing > 0 && FINGER_BONES.has(d.bone)) {
        const previous = this.prevLocal.get(d.bone);
        if (previous) qLocal = previous.clone().slerp(qLocal, 1 - o.fingerSmoothing);
        this.prevLocal.set(d.bone, qLocal.clone());
      }

      pose[d.bone] = { rotation: [qLocal.x, qLocal.y, qLocal.z, qLocal.w] };
      Rworld.set(d.bone, Rparent.clone().multiply(qLocal));
    }

    // Hands out of each other. The wrists are on target by here and the hands
    // can still be inside one another, because a wrist is a point and a hand is
    // not — see handClearance.ts.
    if (this.clearance > 0 && o.armIK && this.armRigs && ikL && ikR) {
      this.clearHands(pose, Rworld, captured, ikL, ikR);
    }

    vrm.humanoid.setNormalizedPose(pose);
    vrm.humanoid.update();
  }

  /**
   * Push the wrist targets apart until the hands clear, and rebuild both arms.
   *
   * Only six bones are touched. The fingers are left exactly as computed: their
   * rotations are relative to the hand, and the hand's world orientation is the
   * captured direction, which a moved elbow cannot change — so the whole hand
   * travels rigidly with its wrist and nothing downstream needs recomputing.
   */
  private clearHands(
    pose: Partial<Record<VRMHumanBoneName, { rotation: [number, number, number, number] }>>,
    Rworld: Map<VRMHumanBoneName, THREE.Quaternion>,
    captured: (name: string) => THREE.Vector3 | null,
    ikL: THREE.Vector3,
    ikR: THREE.Vector3,
  ): void {
    // Forward kinematics in the Rworld frame. Distances are what this pass
    // reads, and those are invariant to where the root sits, so the hips go at
    // the origin and no rig update is needed to measure.
    const fkCache = new Map<VRMHumanBoneName, THREE.Vector3>([[V.Hips, new THREE.Vector3()]]);
    const identity = new THREE.Quaternion();
    const fk = (bone: VRMHumanBoneName): THREE.Vector3 => {
      const hit = fkCache.get(bone);
      if (hit) return hit;
      const parent = PARENT_OF.get(bone);
      const offset = this.restLocal.get(bone);
      const base = parent ? fk(parent) : new THREE.Vector3();
      const out = !parent || !offset
        ? base.clone()
        : base.clone().add(offset.clone().applyQuaternion(Rworld.get(parent) ?? identity));
      fkCache.set(bone, out);
      return out;
    };
    const points = (side: 'l' | 'r'): THREE.Vector3[] => {
      const out: THREE.Vector3[] = [];
      for (const bone of HAND_POINTS[side]) {
        if (!this.restLocal.has(bone)) continue;
        const p = fk(bone);
        out.push(p);
        // A fingertip is not a bone. Extending the distal by its own length
        // reaches one, and the tips are what actually meet first.
        const offset = this.restLocal.get(bone);
        if (DISTAL_TIPS.has(bone) && offset) {
          out.push(p.clone().add(offset.clone().applyQuaternion(Rworld.get(bone) ?? identity)));
        }
      }
      return out;
    };

    const left = points('l');
    const right = points('r');
    if (left.length === 0 || right.length === 0) return;

    // Push along the closest pair's own direction — the wrist axis separates
    // the hands sideways while they collide in depth. Smoothed toward it rather
    // than snapped, because the closest pair jumps between bones; see
    // handClearance.ts.
    const raw = closestPairAxis(left, right, this.clearance, _axis);
    if (!raw) { this.pushAxis = null; return; } // clear: forget the axis too
    if (!this.pushAxis) {
      this.pushAxis = raw.clone();
    } else {
      this.pushAxis.lerp(raw, AXIS_FOLLOW);
      // A near-cancelling blend has no direction left to normalise. That means
      // the pair genuinely reversed, so follow it rather than keep a stale axis.
      if (this.pushAxis.lengthSq() < 0.01) this.pushAxis.copy(raw);
      else this.pushAxis.normalize();
    }

    const delta = pushToClear(left, right, this.pushAxis, this.clearance, MAX_CLEARANCE_PUSH);
    if (delta <= 0) return;
    _axis.copy(this.pushAxis);

    const rebuild = (side: 'l' | 'r', elbowHint: THREE.Vector3, sign: number): void => {
      const rig = side === 'l' ? this.armRigs!.left : this.armRigs!.right;
      const shoulder = captured(`${side}Shoulder`);
      const wrist = captured(`${side}Wrist`);
      if (!shoulder || !wrist) return;
      _shift.copy(_axis).multiplyScalar((sign * delta) / 2);
      const target = wrist.clone().add(_shift);
      const elbow = solveElbow(shoulder, target, elbowHint, rig.upper, rig.fore, new THREE.Vector3());
      // Only the elbow and the wrist move; every other captured joint is read
      // unchanged, so the hand's direction — and with it the whole handshape —
      // is exactly what it was.
      const moved = (name: string): THREE.Vector3 | null => {
        if (name === `${side}Elbow`) return elbow;
        if (name === `${side}Wrist`) return target;
        return captured(name);
      };
      let Rparent = Rworld.get(V.Chest) ?? identity;
      for (const d of ARM_CHAIN[side]) {
        const q = this.boneRotation(d, Rparent, moved);
        if (!q) { Rparent = Rworld.get(d.bone) ?? Rparent; continue; }
        pose[d.bone] = { rotation: [q.x, q.y, q.z, q.w] };
        Rparent = Rparent.clone().multiply(q);
        Rworld.set(d.bone, Rparent);
      }
    };
    rebuild('l', ikL, +1);
    rebuild('r', ikR, -1);
  }
}
