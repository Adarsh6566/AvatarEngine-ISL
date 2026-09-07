/**
 * PlaybackSpeedControl — speed button at bottom-right, opening a menu.
 *
 * It used to cycle on click, which was tolerable at five steps and poor at
 * eight: with the slow speeds ordered below normal, reaching 0.25x from 1x cost
 * five clicks. Slowing down is what a learner reaches for most, so the common
 * case had become the most expensive one. A menu makes every speed one click
 * and shows the whole ladder at once instead of hiding it behind repetition.
 *
 * Notifies the composition root via onChange so the Sequencer and
 * AnimationController stay in sync (mixer timeScale + hold timing).
 *
 * The trigger keeps the .speed-control class and is otherwise unchanged,
 * because index.html and signer.html each position and style that class
 * themselves. The menu is appended to <body> and placed from the trigger's box,
 * so neither page's CSS has to know it exists.
 */
import { APP_CONFIG } from '../config/appConfig';

export interface PlaybackSpeedControlOptions {
  /** Called whenever the speed changes. */
  onChange: (speed: number) => void;
  /** Steps to offer. Defaults to config.yaml animation.playback_speeds. */
  speeds?: readonly number[];
  /** Initial speed. Defaults to config.yaml animation.default_speed. */
  initial?: number;
}

const DEFAULT_SPEEDS = APP_CONFIG.speeds as readonly number[];

const STYLE_ID = 'speed-menu-styles';

/**
 * Injected once.
 *
 * Written entirely through each page's own tokens, with the literal fallback
 * set to whatever the other page hardcodes. index.html and signer.html declare
 * overlapping but not identical token sets — signer.html has --accent, index
 * calls the same brick red --red; index has --hairline and --font-mono, signer
 * has neither — so every value here resolves per page without either page's
 * CSS needing to change.
 *
 * The panel deliberately copies the trigger's frosted-white material rather
 * than using --paper: on index.html --paper IS the page ground, so a panel
 * painted with it would rely on its border alone to separate from the page.
 */
const MENU_CSS = `
.speed-menu {
  position: fixed;
  z-index: 60;
  margin: 0;
  padding: 5px;
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 84px;
  /* Height is capped by place() to the room above the trigger; this is what
     lets the overflow be reached rather than clipped. */
  overflow-y: auto;
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: blur(20px) saturate(1.4);
  border: 1px solid var(--hairline, rgba(22, 19, 15, 0.12));
  border-radius: 14px;
  box-shadow:
    0 1px 2px rgba(22, 19, 15, 0.04),
    0 14px 36px -12px rgba(22, 19, 15, 0.26);
}
.speed-menu[hidden] { display: none; }
.speed-menu__item {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  padding: 7px 11px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--ink, #16130f);
  /* Matches the trigger, which is mono on index.html and inherited on signer. */
  font-family: var(--font-mono, inherit);
  font-size: 0.8125rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  font-variant-numeric: tabular-nums;
  text-align: left;
  cursor: pointer;
}
.speed-menu__item:hover { background: rgba(22, 19, 15, 0.06); }
.speed-menu__item:focus-visible {
  outline: 2px solid var(--accent, var(--red, #b4443a));
  outline-offset: -2px;
}
.speed-menu__item[aria-checked="true"] { color: var(--accent, var(--red, #b4443a)); }
/* The tick holds its width on every row so labels do not shift sideways as the
   selection moves. */
.speed-menu__tick { flex: 0 0 9px; font-size: 0.75rem; }
.speed-menu__item[aria-checked="true"] .speed-menu__tick::before { content: "\\2713"; }
`;

function ensureStyles(): void {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = MENU_CSS;
  document.head.append(style);
}

/** 0.25 -> "0.25x". Number formatting keeps 1 as "1x", not "1.00x". */
const label = (speed: number) => `${speed}x`;

export class PlaybackSpeedControl {
  private readonly button: HTMLButtonElement;
  private readonly menu: HTMLDivElement;
  private readonly items: HTMLButtonElement[] = [];
  private readonly speeds: readonly number[];
  private index: number;
  private readonly onChange: (speed: number) => void;
  private open = false;

  constructor(parent: HTMLElement, options: PlaybackSpeedControlOptions) {
    this.speeds = options.speeds ?? DEFAULT_SPEEDS;
    this.onChange = options.onChange;
    const initial = options.initial ?? APP_CONFIG.defaultSpeed;
    this.index = Math.max(0, this.speeds.indexOf(initial));

    ensureStyles();

    this.button = document.createElement('button');
    this.button.type = 'button';
    this.button.className = 'speed-control';
    this.button.setAttribute('aria-haspopup', 'menu');
    this.button.setAttribute('aria-expanded', 'false');
    this.button.setAttribute('title', 'Playback speed');

    this.menu = document.createElement('div');
    this.menu.className = 'speed-menu';
    this.menu.setAttribute('role', 'menu');
    this.menu.setAttribute('aria-label', 'Playback speed');
    this.menu.hidden = true;

    this.speeds.forEach((speed, i) => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'speed-menu__item';
      item.setAttribute('role', 'menuitemradio');
      item.tabIndex = -1;
      const tick = document.createElement('span');
      tick.className = 'speed-menu__tick';
      tick.setAttribute('aria-hidden', 'true');
      item.append(tick, document.createTextNode(label(speed)));
      item.addEventListener('click', () => this.select(i));
      this.items.push(item);
      this.menu.append(item);
    });

    this.button.addEventListener('click', (event) => {
      // Without this the document listener below sees the same click and
      // closes the menu the moment it opens.
      event.stopPropagation();
      this.open ? this.close() : this.show();
    });
    this.menu.addEventListener('keydown', (event) => this.onMenuKey(event));

    document.addEventListener('click', (event) => {
      if (!this.open) return;
      if (!this.menu.contains(event.target as Node)) this.close();
    });
    document.addEventListener('keydown', (event) => {
      if (this.open && event.key === 'Escape') {
        this.close();
        this.button.focus();
      }
    });
    // The menu is placed from the trigger's box, which moves with the viewport;
    // reposition rather than leave it stranded. Capture catches scrolls inside
    // the page's own scrolling panels, not just the window.
    window.addEventListener('resize', () => this.reposition());
    window.addEventListener('scroll', () => this.reposition(), true);

    this.refresh();
    parent.append(this.button);
    document.body.append(this.menu);
  }

  /** Current speed multiplier (e.g. 0.25, 1, 5). */
  get value(): number {
    return this.speeds[this.index] ?? 1;
  }

  private select(i: number): void {
    this.index = i;
    this.refresh();
    this.close();
    this.button.focus();
    this.onChange(this.value);
  }

  /** Push current state to the trigger label and the checked item. */
  private refresh(): void {
    const speed = this.value;
    this.button.textContent = label(speed);
    this.button.setAttribute('aria-label', `Playback speed ${label(speed)}`);
    this.items.forEach((item, i) => item.setAttribute('aria-checked', String(i === this.index)));
  }

  private show(): void {
    this.open = true;
    this.menu.hidden = false;
    this.button.setAttribute('aria-expanded', 'true');
    this.place();
    this.items[this.index]?.focus();
  }

  private close(): void {
    this.open = false;
    this.menu.hidden = true;
    this.button.setAttribute('aria-expanded', 'false');
  }

  private reposition(): void {
    if (this.open) this.place();
  }

  /**
   * Sit the menu above the trigger with their right edges aligned.
   *
   * Both edges are anchored — bottom and right — rather than a top and left
   * computed from the menu's measured size. That is deliberate: the height is
   * capped below, and a cap that engages after this runs would leave any
   * measured-height arithmetic stale and push the panel off screen. Anchoring
   * the two edges that are actually fixed leaves the browser to resolve the
   * rest, so the panel cannot be misplaced by its own resizing.
   *
   * Eight rows come to ~290px, and a phone held in landscape has around 375px
   * of height in total, so the ladder genuinely can outgrow the space above the
   * button. Capping it to that space (with overflow-y: auto above) keeps the
   * fastest speeds scrollable-to instead of clipped off the top.
   */
  private place(): void {
    const box = this.button.getBoundingClientRect();
    const gap = 8;
    this.menu.style.bottom = `${Math.round(window.innerHeight - box.top + gap)}px`;
    this.menu.style.right = `${Math.round(window.innerWidth - box.right)}px`;
    this.menu.style.maxHeight = `${Math.max(96, Math.round(box.top - gap * 2))}px`;
  }

  private onMenuKey(event: KeyboardEvent): void {
    const last = this.items.length - 1;
    const current = this.items.indexOf(document.activeElement as HTMLButtonElement);
    const focus = (i: number) => {
      event.preventDefault();
      this.items[Math.max(0, Math.min(last, i))]?.focus();
    };
    switch (event.key) {
      case 'ArrowDown': focus(current < 0 ? 0 : current + 1); break;
      case 'ArrowUp': focus(current < 0 ? last : current - 1); break;
      case 'Home': focus(0); break;
      case 'End': focus(last); break;
      case 'Tab':
        // An open menu should not leak focus back into the page behind it.
        event.preventDefault();
        this.close();
        this.button.focus();
        break;
      default: break;
    }
  }
}
