import { AnimationMixer, LoopOnce, type AnimationAction, type AnimationClip, type Object3D } from 'three';
import type { GestureCommand } from '../gestures/GestureCommand';
import { GestureLibrary } from './GestureLibrary';

/**
 * HumanoidRig — the abstraction AnimationController uses to reach the avatar.
 * AvatarController injects a VRM-backed adapter via attach(); the controller
 * itself never imports @pixiv/three-vrm.
 */
export interface HumanoidRig {
  /** Root object the AnimationMixer animates (the avatar's bones live under it). */
  getRoot(): Object3D;
}

import { APP_CONFIG } from "../../config/appConfig";

/**
 * Cross-fade window between gestures, in seconds (config.yaml: animation.gesture_fade_seconds).
 *
 * Exported because playback timing depends on it: the Sequencer overlaps its
 * hold by this much so the next sign starts blending in as the previous one
 * lands, instead of after it has already settled.
 */
export const GESTURE_FADE_SECONDS = APP_CONFIG.animation.gestureFade;

/** A handle to a single playback started by {@link AnimationController.play}. */
export interface PlaybackHandle {
  readonly id: string;
  readonly command: GestureCommand;
}

/**
 * AnimationController — turns a validated GestureCommand into avatar motion by
 * playing an AnimationClip on a THREE.AnimationMixer.
 *
 * Responsibility (single): own animation playback for one avatar — the mixer,
 * the per-gesture actions, and the playback lifecycle. Clips are supplied from
 * outside via registerClip() (e.g. VRMA clips loaded by VRMAGestureLoader), so
 * this class imports only three.js core, never @pixiv/three-vrm. Callers never
 * see the mixer.
 */
export class AnimationController {
  private counter = 0;
  private mixer: AnimationMixer | null = null;
  private readonly library = new GestureLibrary();
  private readonly actions = new Map<string, AnimationAction>();

  /** The gesture currently holding the body, so the next one can blend from it. */
  private current: AnimationAction | null = null;

  private playbackRate = 1;

  /** Bind to a loaded avatar: create the mixer over the rig's root. */
  attach(rig: HumanoidRig): void {
    this.mixer = new AnimationMixer(rig.getRoot());
    this.mixer.timeScale = this.playbackRate;
    this.actions.clear();
    this.current = null;
  }

  /** Scale animation playback (1 = normal, 5 = 5×). Affects all clips via mixer timeScale. */
  setPlaybackRate(rate: number): void {
    this.playbackRate = Math.max(0.1, rate);
    if (this.mixer) this.mixer.timeScale = this.playbackRate;
  }

  get playbackRateValue(): number {
    return this.playbackRate;
  }

  /**
   * Register an externally-loaded clip (e.g. a VRMA clip from VRMAGestureLoader)
   * under a gesture id. Re-registering an id drops its cached action so the new
   * clip takes effect.
   */
  registerClip(id: string, clip: AnimationClip): void {
    this.library.register(id, clip);
    this.actions.delete(id);
  }

  play(command: GestureCommand, fadeSeconds: number = GESTURE_FADE_SECONDS): PlaybackHandle {
    const label = this.validate(command);
    const handle: PlaybackHandle = { id: `playback-${++this.counter}`, command };

    const next = this.actionFor(command.id);
    if (!next) {
      console.warn(`[AnimationController] no clip registered for "${command.id}" (${handle.id})`);
      return handle;
    }

    // Cross-fade rather than cut. The outgoing action fades 1 -> 0 while the
    // incoming fades 0 -> 1 over the same window, so their weights sum to ~1
    // throughout and the body eases between poses instead of teleporting. The
    // window is caller-tunable — fingerspelling passes a much shorter one.
    const previous = this.current;
    if (previous && previous !== next) {
      previous.fadeOut(fadeSeconds);
    }

    next.reset();
    next.fadeIn(fadeSeconds);
    next.play();

    this.current = next;
    console.info(`[AnimationController] playing ${label} (${handle.id})`);

    return handle;
  }

  /**
   * Ease out of the current gesture back to the avatar's rest pose.
   *
   * Called when a sequence ends. Without it the avatar holds the final sign
   * indefinitely; with it, it settles. Slower than a gesture-to-gesture fade —
   * relaxing should read as coming to rest, not as another sign.
   */
  relax(): void {
    this.current?.fadeOut(GESTURE_FADE_SECONDS * 2.5);
    this.current = null;
  }

  /**
   * Length of a registered clip in seconds, or null if we have no such clip.
   *
   * This is the authoritative duration — it comes from the asset itself, unlike
   * the hand-maintained numbers in the motion manifest, which drift.
   */
  getDuration(id: string): number | null {
    return this.library.get(id)?.duration ?? null;
  }

  /** Advance the mixer one frame. Driven by AvatarController before vrm.update(). */
  update(delta: number): void {
    this.mixer?.update(delta);
  }

  /** Stop playback and release mixer/actions. Called by AvatarController on unload. */
  dispose(): void {
    this.mixer?.stopAllAction();
    this.mixer = null;
    this.actions.clear();
    this.current = null;
  }

  /** Lazily create and memoize the AnimationAction for a gesture id. */
  private actionFor(id: string): AnimationAction | null {
    const existing = this.actions.get(id);
    if (existing) return existing;

    const clip = this.library.get(id);
    if (!clip || !this.mixer) return null;

    const action = this.mixer.clipAction(clip);
    action.setLoop(LoopOnce, 1); // one-shot; sign gestures do not loop

    // Hold the final frame instead of releasing the pose. Without this, a
    // finished LoopOnce action stops being applied and every bone snaps back to
    // the bind pose the instant the sign ends — the single worst source of
    // "snappy" playback.
    action.clampWhenFinished = true;

    this.actions.set(id, action);
    return action;
  }

  private validate(command: GestureCommand): string {
    if (typeof command?.id !== 'string' || command.id.length === 0) {
      throw new Error('[AnimationController] invalid command: "id" must be a non-empty string');
    }

    switch (command.type) {
      case 'sign':
        return `sign "${command.id}"`;
      default:
        throw new Error(`[AnimationController] unknown command type: ${String(command.type)}`);
    }
  }
}
