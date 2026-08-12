import type { RenderEngine } from '../core/RenderEngine';
import type { SkeletonStream } from './SkeletonStream';

/**
 * SkeletonRenderer — a hot-swappable consumer of a SkeletonStream.
 *
 * A renderer knows how to draw one frame of the canonical stream: neon lines
 * (NeonLineRenderer), a VRM avatar (future), a still-frame painter (future).
 * Renderers never time playback themselves — the SkeletonPlayer owns time and
 * pushes frame numbers — so swapping renderers mid-sequence resumes at the
 * same frame and cannot corrupt the motion.
 */
export interface SkeletonRenderer {
  /** Stable discriminator for registries / UI ("neon", "vrm", ...). */
  readonly kind: string;

  /** Bind a new stream. Renderers may preallocate geometry here. */
  setStream(stream: SkeletonStream): void;

  /** Draw frame `index` (0-based). Missing joints are skipped, never fabricated. */
  setFrame(index: number): void;

  /** Add the renderer's scene objects and start any per-frame work. */
  attach(engine: RenderEngine): void;

  /** Remove the renderer's scene objects (without disposing resources). */
  detach(): void;

  /** Release GPU resources. Always call on teardown. */
  dispose(): void;
}

/**
 * SkeletonPlayer — shared playback clock for a SkeletonRenderer.
 *
 * Advances a stream in real time (fps-scaled) and pushes each frame to the
 * renderer. Because time lives here rather than in the renderer, playback is
 * renderer-independent: the neon viewer and a future VRM renderer both see
 * exactly the same sequence of frames.
 */
export class SkeletonPlayer {
  private readonly renderer: SkeletonRenderer;
  private stream: SkeletonStream | null = null;
  private cursor = 0; // fractional frame index
  private playing = false;
  loop = true;

  constructor(renderer: SkeletonRenderer) {
    this.renderer = renderer;
  }

  setStream(stream: SkeletonStream): void {
    this.stream = stream;
    this.cursor = 0;
    this.renderer.setStream(stream);
    this.renderer.setFrame(0);
  }

  play(): void {
    this.playing = true;
  }

  pause(): void {
    this.playing = false;
  }

  /** Invert play state. Returns the new state. */
  toggle(): boolean {
    this.playing = !this.playing;
    return this.playing;
  }

  get isPlaying(): boolean {
    return this.playing;
  }

  get currentIndex(): number {
    return Math.floor(this.cursor);
  }

  get frameCount(): number {
    return this.stream?.frames.length ?? 0;
  }

  get currentTime(): number {
    return this.stream ? this.cursor / this.stream.fps : 0;
  }

  get duration(): number {
    return this.stream?.duration ?? 0;
  }

  seek(index: number): void {
    const n = this.frameCount;
    if (n === 0) return;
    this.cursor = Math.min(Math.max(index, 0), n - 1);
    this.renderer.setFrame(this.currentIndex);
  }

  /** Advance playback by a real-time delta (seconds) and render the new frame. */
  step(delta: number): void {
    const s = this.stream;
    if (!s || !this.playing) return;
    const n = s.frames.length;
    if (n <= 1) return;

    const next = this.cursor + delta * s.fps;
    if (next >= n - 1e-9) {
      if (this.loop) {
        this.cursor = ((next % n) + n) % n;
      } else {
        this.cursor = n - 1;
        this.playing = false;
        this.renderer.setFrame(this.currentIndex);
        return;
      }
    } else {
      this.cursor = next;
    }
    this.renderer.setFrame(this.currentIndex);
  }
}
