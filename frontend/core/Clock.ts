import * as THREE from 'three';

/**
 * Shared engine clock.
 *
 * Provides delta time for frame-independent animations while hiding
 * THREE.Clock behind a simple interface.
 */
export class Clock {
  private readonly source = new THREE.Clock();
  private elapsed = 0;
  private paused = false;

  // Hard cap on a single frame's delta 
  private readonly maxDelta = 0.1;

  /** Advance the clock one frame and return the (clamped) delta in seconds.
   *  Returns 0 while paused so all animation freezes cleanly. */
  tick(): number {
    const raw = this.source.getDelta();
    if (this.paused) return 0;
    const delta = Math.min(raw, this.maxDelta);
    this.elapsed += delta;
    return delta;
  }

  /** Total un-paused seconds since start. Useful for looping/idle animations. */
  getElapsed(): number {
    return this.elapsed;
  }

  pause(): void {
    this.paused = true;
  }

  resume(): void {
    this.paused = false;
  }
}
