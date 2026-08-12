import type { AnimationClip } from 'three';

/**
 * GestureLibrary — maps a gesture id (e.g. "TEST", "HELLO") to the AnimationClip
 * that performs it.
 *
 * Why it exists: it is the single place the engine learns "which clip plays for
 * which sign," so AnimationController never hardcodes gesture-specific branches.
 * Clips are plain THREE.AnimationClip objects — no @pixiv/three-vrm here — so the
 * temporary TEST clip and future imported .vrma clips register identically.
 */
export class GestureLibrary {
  private readonly clips = new Map<string, AnimationClip>();

  register(id: string, clip: AnimationClip): void {
    this.clips.set(id, clip);
  }

  get(id: string): AnimationClip | undefined {
    return this.clips.get(id);
  }
}
