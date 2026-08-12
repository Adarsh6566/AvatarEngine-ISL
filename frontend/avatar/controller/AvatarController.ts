import type { RenderEngine } from '../../core/RenderEngine';
import { VrmLoader } from '../loading/VrmLoader';
import { AnimationController, type PlaybackHandle, type HumanoidRig } from '../animation/AnimationController';
import { ExpressionController, type ExpressionBackend } from '../expressions/ExpressionController';
import type { GestureCommand } from '../gestures/GestureCommand';
import * as THREE from 'three';
import { VRMUtils, type VRM } from '@pixiv/three-vrm';
import { VRMAGestureLoader } from '../loading/VRMAGestureLoader';
import { GestureRegistry, type GestureManifestEntry } from '../gestures/GestureRegistry';
import { APP_CONFIG } from '../../config/appConfig';

/**
 * AvatarController — the ONLY public class of the avatar module.
 *
 * Responsibility (single): be the facade. It owns the avatar's lifecycle and
 * orchestrates the specialist controllers, exposing one small, intent-level API
 * (load / playGesture / setExpression / dispose). Everything else in the module
 * — VrmLoader, VRMAGestureLoader, AnimationController, ExpressionController, the
 * VRM itself — is a private collaborator the outside world never names.
 */
export class AvatarController {
  private readonly engine: RenderEngine;
  private readonly loader = new VrmLoader();
  private readonly gestureLoader = new VRMAGestureLoader();
  private readonly animation = new AnimationController();
  private readonly expressions = new ExpressionController();
  private readonly registry = new GestureRegistry();

  private vrm: VRM | null = null;
  private unsubscribeTick: (() => void) | null = null;

  constructor(engine: RenderEngine) {
    this.engine = engine;
  }

  /**
   * Load (or replace) the avatar. Wires the VRM into the scene, injects the
   * expression + animation backends, loads this avatar's VRMA gesture clips, and
   * subscribes the per-frame tick. Rejects if the VRM or a gesture fails to load.
   */
  async load(url: string): Promise<void> {
    this.unloadCurrent(); // support hot-swapping avatars

    const vrm = await this.loader.load(url);
    this.vrm = vrm;
    // Lift avatar slightly so feet clear the bottom input bar overlay.
    vrm.scene.position.y = 0.2;
    this.engine.add(vrm.scene);

    // Inject the concrete backends — the only places three-vrm is touched.
    this.expressions.attach(this.createExpressionBackend(vrm));
    this.animation.attach(this.createHumanoidRig(vrm));

    // Load this avatar's VRMA gesture clips and register them for playback.
    await this.loadGestures(vrm);

    // Replace the T-pose bind pose with a natural resting pose (arms down,
    // hands relaxed) so the avatar never holds a T-pose when idle.
    this.applyNaturalPose(vrm);

    // AvatarController owns the per-frame tick: advance animation, then let the
    // VRM copy the animated normalized bones onto the raw skeleton.
    this.unsubscribeTick = this.engine.onUpdate((delta) => {
      this.animation.update(delta);
      vrm.update(delta);
    });
  }

  /** Perform a gesture. Delegates to AnimationController; returns its handle.
   *  `fadeSeconds` overrides the crossfade window (fingerspelling uses a short one). */
  playGesture(command: GestureCommand, fadeSeconds?: number): PlaybackHandle {
    return this.animation.play(command, fadeSeconds);
  }

  /**
   * Length of a gesture's clip in seconds, or null if it is not registered.
   *
   * Callers should time playback on this rather than on a hand-written number:
   * it comes from the asset itself and cannot drift.
   */
  getGestureDuration(id: string): number | null {
    return this.animation.getDuration(id);
  }

  /** Ease out of the current gesture back to rest. Call when a sequence ends. */
  relax(): void {
    this.animation.relax();
  }

  /** Scale animation playback rate (1 = normal). Delegates to AnimationController. */
  setPlaybackRate(rate: number): void {
    this.animation.setPlaybackRate(rate);
  }

  /** Set a facial / non-manual expression by name. Delegates to ExpressionController. */
  setExpression(name: string): void {
    this.expressions.setExpression(name);
  }

  /** Tear down: stop the tick, release animation resources, and free the avatar. */
  dispose(): void {
    this.unloadCurrent();
  }

  /**
   * Load and register every gesture the registry exposes with bounded
   * concurrency. Word signs (HELLO/BYE/…) are prioritized so the core
   * vocabulary is usable first; letters fill in after. One bad file never
   * blocks the rest (allSettled per batch).
   */
  private async loadGestures(vrm: VRM): Promise<void> {
    const gestures = this.registry.getAll();
    const wordOrder: readonly string[] = APP_CONFIG.avatar.wordPriority;
    const sorted = [...gestures].sort((a, b) => {
      const ai = wordOrder.indexOf(a.id);
      const bi = wordOrder.indexOf(b.id);
      if (ai !== -1 && bi !== -1) return ai - bi;
      if (ai !== -1) return -1;
      if (bi !== -1) return 1;
      return 0;
    });

    const CONCURRENCY = APP_CONFIG.avatar.concurrency;
    let registered = 0;

    for (let i = 0; i < sorted.length; i += CONCURRENCY) {
      const batch = sorted.slice(i, i + CONCURRENCY);
      const results = await Promise.allSettled(batch.map((entry) => this.registerGesture(vrm, entry)));
      for (const r of results) {
        if (r.status === 'fulfilled' && r.value) registered += 1;
        else if (r.status === 'rejected') console.warn('[AvatarController] batch load rejected', r.reason);
      }
    }

    console.info(`[AvatarController] gestures ready: ${registered}/${gestures.length} registered`);
    if (registered < gestures.length) {
      console.warn(`[AvatarController] ${gestures.length - registered} gesture(s) failed — caption-only fallback will be used`);
    }
  }

  /** Load one manifest entry and register its clip. Returns whether it succeeded. */
  private async registerGesture(vrm: VRM, entry: GestureManifestEntry): Promise<boolean> {
    try {
      const clip = await this.gestureLoader.load(vrm, entry.url);
      this.animation.registerClip(entry.id, clip);
      console.info(`[AvatarController] gesture "${entry.id}" registered (${entry.url})`);
      return true;
    } catch (error) {
      console.warn(`[AvatarController] gesture "${entry.id}" failed to load (${entry.url}):`, error);
      return false;
    }
  }

  private unloadCurrent(): void {
    this.unsubscribeTick?.();
    this.unsubscribeTick = null;
    this.animation.dispose();

    if (this.vrm) {
      this.engine.remove(this.vrm.scene);
      VRMUtils.deepDispose(this.vrm.scene);
      this.vrm = null;
    }
  }

  private createExpressionBackend(vrm: VRM): ExpressionBackend {
    return {
      applyExpression(name: string): void {
        vrm.expressionManager?.setValue(name, 1.0);
      },
    };
  }

  /**
   * Natural resting pose — arms at sides, slight elbow bend, hands relaxed.
   * Applied via normalized humanoid pose (delta from T-pose), so it survives
   * as the fallback whenever the mixer has no active gesture.
   */
  private applyNaturalPose(vrm: VRM): void {
    const toQuat = (euler: THREE.Euler): [number, number, number, number] => {
      const q = new THREE.Quaternion().setFromEuler(euler);
      return [q.x, q.y, q.z, q.w];
    };

    // T-pose has arms horizontal (X axis). Rotating around Z brings them down.
    // 90° is vertical at sides; 5-10° gap means 80-85° down from horizontal.
    vrm.humanoid.setNormalizedPose({
      leftUpperArm: { rotation: toQuat(new THREE.Euler(0, 0, -1.396)) }, // ~-80° (10° from torso)
      rightUpperArm: { rotation: toQuat(new THREE.Euler(0, 0, 1.396)) }, // ~80°
      leftLowerArm: { rotation: toQuat(new THREE.Euler(0, 0.06, 0.05)) },
      rightLowerArm: { rotation: toQuat(new THREE.Euler(0, -0.06, -0.05)) },
      leftHand: { rotation: toQuat(new THREE.Euler(0.04, 0, -0.04)) },
      rightHand: { rotation: toQuat(new THREE.Euler(0.04, 0, 0.04)) },
    });
    // Push the pose to raw bones immediately so first frame is not T-pose.
    vrm.humanoid.update();
  }

  private createHumanoidRig(vrm: VRM): HumanoidRig {
    // The mixer animates vrm.scene; VRMA clips are retargeted onto the normalized
    // bones under it, and vrm.update() copies those onto the raw skeleton.
    return { getRoot: () => vrm.scene };
  }
}
