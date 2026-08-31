import * as THREE from 'three';
import { type VRM } from '@pixiv/three-vrm';
import type { RenderEngine } from '../core/RenderEngine';
import { VrmLoader } from '../avatar/loading/VrmLoader';
import { SkeletonRetargeter, type RetargetOptions } from '../avatar/animation/SkeletonRetargeter';
import type { SkeletonStream } from './SkeletonStream';
import type { SkeletonRenderer } from './SkeletonRenderer';

/**
 * VrmRenderer — drives the signing VRM avatar from a SkeletonStream.
 *
 * A second first-class SkeletonRenderer alongside NeonLineRenderer: same stream
 * in, a rigged humanoid out. It owns the scene-side concerns — loading its own
 * VRM, lighting it, attaching to the engine, stepping frames — and delegates the
 * position→rotation math to SkeletonRetargeter, which AvatarController also uses
 * so the viewer and the app cannot drift apart.
 *
 * VRM loading is async; setFrame is a no-op until the model is ready, then the
 * pending frame is applied. This renderer does NOT modify any .vrma playback.
 */

/**
 * DEBUG coordinate knobs, read from the URL so we can change ONE variable at a
 * time without editing code:
 *    sx,sy,sz = ±1  → negate an input axis (default 1)
 *    swap=xz|xy|yz  → swap two input axes (default none)
 *    root=torso     → derive the hips frame from the torso (default: identity)
 *    legs=1         → drive the legs (default: off)
 *    body=1         → drive torso + head (default: off)
 *    fingers=full|prox|off
 *  e.g. ?src=...&renderer=vrm&sz=-1&root=torso
 *
 * Viewer-only: the app constructs SkeletonRetargeter with its defaults, so no
 * URL parameter can change how the product signs.
 */
function readDebugOptions(): Partial<RetargetOptions> {
  const q = new URLSearchParams(window.location.search);
  const sign = (k: string) => (q.get(k) === '-1' ? -1 : 1);
  return {
    sx: sign('sx'),
    sy: sign('sy'),
    sz: sign('sz'),
    swap: q.get('swap') ?? '',
    // Root upright by DEFAULT: a sign-language avatar stands vertical and faces
    // the viewer. Deriving the hip frame from the (noisy) torso lets the whole
    // body tilt/lean, which we don't want. Pass ?root=torso to follow the torso.
    rootIdentity: q.get('root') !== 'torso',
    // Legs off by default: MediaPipe lower-body DEPTH is unreliable (ankles get
    // shoved ~0.5 behind the hips), so driving them bends the shins backward.
    // A signing avatar just stands; enable with ?legs=1 if the capture is clean.
    driveLegs: q.get('legs') === '1',
    // Torso + head off by default too: this is a SIGN-LANGUAGE avatar — only the
    // arms, hands and fingers carry meaning, and spine/neck depth is noisy. The
    // whole body still ORIENTS via the hips (Rhips); it just doesn't bend/twist.
    // Enable full torso+head with ?body=1. (Capture keeps all joints regardless.)
    driveBody: q.get('body') === '1',
    // Finger driving mode: 'full' (proximal+intermediate), 'prox' (proximal
    // only — the intermediate bone left at rest), 'off' (fingers at rest).
    fingerMode: (q.get('fingers') ?? 'full') as 'full' | 'prox' | 'off',
  };
}

export class VrmRenderer implements SkeletonRenderer {
  readonly kind = 'vrm';

  private readonly group = new THREE.Group();
  private vrm: VRM | null = null;
  private engine: RenderEngine | null = null;
  private unsub: (() => void) | null = null;

  private stream: SkeletonStream | null = null;
  private pendingFrame = 0;

  private readonly retargeter = new SkeletonRetargeter(readDebugOptions());

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
    // Measure rest BEFORE anything poses the model — this renderer applies no
    // resting pose of its own, so the VRM is still in its T-pose here.
    this.retargeter.captureRest(vrm);
    if (this.engine) this.registerUpdate();
    if (this.stream) this.setFrame(this.pendingFrame);
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
    this.retargeter.applyPose(vrm, frame.joints);
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
