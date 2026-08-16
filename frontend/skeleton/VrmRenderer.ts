import * as THREE from 'three';
import { VRMHumanBoneName, type VRM } from '@pixiv/three-vrm';
import type { RenderEngine } from '../core/RenderEngine';
import { VrmLoader } from '../avatar/loading/VrmLoader';
import type { SkeletonStream } from './SkeletonStream';
import type { SkeletonRenderer } from './SkeletonRenderer';

/**
 * VrmRenderer — drives the signing VRM avatar from a SkeletonStream.
 *
 * A second first-class SkeletonRenderer alongside NeonLineRenderer: same stream
 * in, a rigged humanoid out. It retargets joint POSITIONS to VRM bone rotations
 * by forward-kinematic SWING extraction — the exact method verified offline in
 * target_rotations.py / skeleton_to_smplx_npz.py:
 *
 *   restDir  = normalize(childRestPos - boneRestPos)      (VRM normalized T-pose)
 *   obsDir   = normalize(childObsPos  - boneObsPos)       (stream, view space)
 *   qLocal   = fromUnitVectors(restDir, Rparent⁻¹ · obsDir)   (local swing)
 *   Rworld   = Rparent · qLocal                           (walk parents→children)
 *
 * Applied via vrm.humanoid.setNormalizedPose (identity = rest), so it uses the
 * same supported path as AvatarController and never touches the raw rig. Swing
 * only (no twist); fingers as coarse as the capture (2 joints/finger here).
 *
 * VRM loading is async; setFrame is a no-op until the model is ready, then the
 * pending frame is applied. This renderer does NOT modify any .vrma playback.
 */

const V = VRMHumanBoneName;

/** One driven bone: which VRM bone, its nearest DRIVEN ancestor (frame parent),
 *  the VRM child used for the rest direction, and the stream joints giving the
 *  observed direction. Order matters: parents precede children. */
interface Drive {
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

const DRIVES: Drive[] = [
  { bone: V.Spine, parent: V.Hips, restChild: V.Chest, from: 'spine', to: 'chest' },
  { bone: V.Chest, parent: V.Spine, restChild: V.Neck, from: 'chest', to: 'neck' },
  { bone: V.Neck, parent: V.Chest, restChild: V.Head, from: 'neck', to: 'head' },
  ...sideDrives('Left', 'l'),
  ...sideDrives('Right', 'r'),
];

const _c = new THREE.Vector3();

export class VrmRenderer implements SkeletonRenderer {
  readonly kind = 'vrm';

  private readonly group = new THREE.Group();
  private vrm: VRM | null = null;
  private engine: RenderEngine | null = null;
  private unsub: (() => void) | null = null;

  private stream: SkeletonStream | null = null;
  private pendingFrame = 0;

  /** Rest bone directions (normalized), captured from the VRM T-pose. */
  private restDir = new Map<VRMHumanBoneName, THREE.Vector3>();
  private rootParentWorldQ = new THREE.Quaternion();

  /** DEBUG coordinate knobs, read from the URL so we can change ONE variable at
   *  a time without editing code:
   *    sx,sy,sz = ±1  → negate an input axis (default 1)
   *    swap=xz|xy|yz  → swap two input axes (default none)
   *    root=id        → force the hips frame to identity (skip torso basis)
   *  e.g. ?src=...&renderer=vrm&sz=-1&root=id */
  private readonly axis = (() => {
    const q = new URLSearchParams(window.location.search);
    const sign = (k: string) => (q.get(k) === '-1' ? -1 : 1);
    return {
      sx: sign('sx'),
      sy: sign('sy'),
      sz: sign('sz'),
      swap: q.get('swap') ?? '',
      rootIdentity: q.get('root') === 'id' || q.get('root') === 'identity',
      // Legs off by default: MediaPipe lower-body DEPTH is unreliable (ankles get
      // shoved ~0.5 behind the hips), so driving them bends the shins backward.
      // A signing avatar just stands; enable with ?legs=1 if the capture is clean.
      driveLegs: q.get('legs') === '1',
      // Finger driving mode: 'full' (proximal+intermediate), 'prox' (proximal
      // only — the intermediate bone left at rest), 'off' (fingers at rest).
      fingerMode: (q.get('fingers') ?? 'full') as 'full' | 'prox' | 'off',
    };
  })();

  /** Lower-body bones skipped unless ?legs=1 (see axis.driveLegs). */
  private static readonly LEG_BONES: ReadonlySet<VRMHumanBoneName> = new Set([
    V.LeftUpperLeg, V.LeftLowerLeg, V.RightUpperLeg, V.RightLowerLeg,
  ]);

  /** Non-proximal finger bones (intermediate + distal), skipped when ?fingers=prox
   *  so only the base knuckle is driven. */
  private static readonly FINGER_NONPROXIMAL: ReadonlySet<VRMHumanBoneName> = new Set([
    V.LeftThumbDistal, V.LeftIndexIntermediate, V.LeftIndexDistal, V.LeftMiddleIntermediate, V.LeftMiddleDistal,
    V.LeftRingIntermediate, V.LeftRingDistal, V.LeftLittleIntermediate, V.LeftLittleDistal,
    V.RightThumbDistal, V.RightIndexIntermediate, V.RightIndexDistal, V.RightMiddleIntermediate, V.RightMiddleDistal,
    V.RightRingIntermediate, V.RightRingDistal, V.RightLittleIntermediate, V.RightLittleDistal,
  ]);

  /** All driven finger bones, skipped when ?fingers=off. */
  private static readonly FINGER_BONES: ReadonlySet<VRMHumanBoneName> = new Set([
    V.LeftThumbProximal, V.LeftThumbDistal, V.LeftIndexProximal, V.LeftMiddleProximal, V.LeftRingProximal, V.LeftLittleProximal,
    V.LeftIndexIntermediate, V.LeftIndexDistal, V.LeftMiddleIntermediate, V.LeftMiddleDistal,
    V.LeftRingIntermediate, V.LeftRingDistal, V.LeftLittleIntermediate, V.LeftLittleDistal,
    V.RightThumbProximal, V.RightThumbDistal, V.RightIndexProximal, V.RightMiddleProximal, V.RightRingProximal, V.RightLittleProximal,
    V.RightIndexIntermediate, V.RightIndexDistal, V.RightMiddleIntermediate, V.RightMiddleDistal,
    V.RightRingIntermediate, V.RightRingDistal, V.RightLittleIntermediate, V.RightLittleDistal,
  ]);

  constructor(url: string) {
    // lights first so the avatar is lit the instant it appears
    const hemi = new THREE.HemisphereLight(0xffffff, 0x334455, 2.2);
    const dir = new THREE.DirectionalLight(0xffffff, 1.4);
    dir.position.set(1, 2, 2);
    this.group.add(hemi, dir);

    new VrmLoader()
      .load(url)
      .then((vrm) => this.onLoaded(vrm))
      .catch((e) => console.error('[VrmRenderer] load failed', e));
  }

  private onLoaded(vrm: VRM): void {
    this.vrm = vrm;
    this.group.add(vrm.scene);
    this.captureRest(vrm);
    if (this.engine) this.registerUpdate();
    if (this.stream) this.setFrame(this.pendingFrame);
  }

  /** Record each driven bone's rest direction from the normalized T-pose. */
  private captureRest(vrm: VRM): void {
    const node = (b: VRMHumanBoneName) => vrm.humanoid.getNormalizedBoneNode(b);
    const worldPos = (b: VRMHumanBoneName): THREE.Vector3 | null => {
      const n = node(b);
      if (!n) return null;
      n.updateWorldMatrix(true, false);
      return n.getWorldPosition(new THREE.Vector3());
    };
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
  }

  setStream(stream: SkeletonStream): void {
    this.stream = stream;
    this.pendingFrame = 0;
    this.setFrame(0);
  }

  setFrame(index: number): void {
    this.pendingFrame = index;
    const vrm = this.vrm;
    const s = this.stream;
    if (!vrm || !s || s.frames.length === 0) return;
    const frame = s.frames[Math.min(Math.max(index, 0), s.frames.length - 1)];
    const J = frame.joints;

    const pos = (name: string): THREE.Vector3 | null => {
      const v = J[name];
      if (!v) return null;
      let x = v[0] * this.axis.sx;
      let y = v[1] * this.axis.sy;
      let z = v[2] * this.axis.sz;
      if (this.axis.swap === 'xz') [x, z] = [z, x];
      else if (this.axis.swap === 'xy') [x, y] = [y, x];
      else if (this.axis.swap === 'yz') [y, z] = [z, y];
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
    let Rhips = new THREE.Quaternion();
    if (!this.axis.rootIdentity && hips && chest && lSh && rSh) {
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
      if (!this.axis.driveLegs && VrmRenderer.LEG_BONES.has(d.bone)) {
        Rworld.set(d.bone, Rparent); // leg left at rest (standing)
        continue;
      }
      const fm = this.axis.fingerMode;
      if (
        (fm === 'off' && VrmRenderer.FINGER_BONES.has(d.bone)) ||
        (fm === 'prox' && VrmRenderer.FINGER_NONPROXIMAL.has(d.bone))
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
      const qLocal = new THREE.Quaternion().setFromUnitVectors(rest, obsLocal);
      pose[d.bone] = { rotation: [qLocal.x, qLocal.y, qLocal.z, qLocal.w] };
      Rworld.set(d.bone, Rparent.clone().multiply(qLocal));
    }

    vrm.humanoid.setNormalizedPose(pose);
    vrm.humanoid.update();
  }

  attach(engine: RenderEngine): void {
    this.engine = engine;
    engine.add(this.group);
    if (this.vrm) this.registerUpdate();
  }

  private registerUpdate(): void {
    this.unsub?.();
    this.unsub = this.engine?.onUpdate((delta) => this.vrm?.update(delta)) ?? null;
  }

  detach(): void {
    this.unsub?.();
    this.unsub = null;
    this.engine?.remove(this.group);
  }

  dispose(): void {
    this.detach();
    if (this.vrm) {
      this.group.remove(this.vrm.scene);
      this.vrm.scene.traverse((o) => {
        const mesh = o as THREE.Mesh;
        mesh.geometry?.dispose?.();
        const mat = mesh.material;
        if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
        else mat?.dispose?.();
      });
    }
  }
}
