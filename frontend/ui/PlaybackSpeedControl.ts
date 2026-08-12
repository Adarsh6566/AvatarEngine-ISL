/**
 * PlaybackSpeedControl — speed button at bottom-right.
 *
 * Cycles through 1x → 2x → 3x → 4x → 5x → 1x on click.
 * Notifies the composition root via onChange so the Sequencer and
 * AnimationController stay in sync (mixer timeScale + hold timing).
 */
import { APP_CONFIG } from "../config/appConfig";

export interface PlaybackSpeedControlOptions {
  /** Called whenever the speed changes. */
  onChange: (speed: number) => void;
  /** Steps to cycle through. Defaults to config.yaml animation.playback_speeds. */
  speeds?: readonly number[];
  /** Initial speed. Defaults to config.yaml animation.default_speed. */
  initial?: number;
}

const DEFAULT_SPEEDS = APP_CONFIG.speeds as readonly number[];

export class PlaybackSpeedControl {
  private readonly button: HTMLButtonElement;
  private readonly speeds: readonly number[];
  private index: number;
  private readonly onChange: (speed: number) => void;

  constructor(parent: HTMLElement, options: PlaybackSpeedControlOptions) {
    this.speeds = options.speeds ?? DEFAULT_SPEEDS;
    this.onChange = options.onChange;
    const initial = options.initial ?? APP_CONFIG.defaultSpeed;
    this.index = Math.max(0, this.speeds.indexOf(initial));

    this.button = document.createElement('button');
    this.button.type = 'button';
    this.button.className = 'speed-control';
    this.button.setAttribute('aria-label', 'Playback speed');
    this.button.setAttribute('title', 'Playback speed');
    this.updateLabel();

    this.button.addEventListener('click', () => {
      this.index = (this.index + 1) % this.speeds.length;
      this.updateLabel();
      this.onChange(this.value);
    });

    parent.append(this.button);
  }

  /** Current speed multiplier (e.g. 1, 2, 5). */
  get value(): number {
    return this.speeds[this.index] ?? 1;
  }

  private updateLabel(): void {
    const speed = this.speeds[this.index] ?? 1;
    this.button.textContent = `${speed}x`;
    this.button.setAttribute('aria-label', `Playback speed ${speed}x`);
  }
}
