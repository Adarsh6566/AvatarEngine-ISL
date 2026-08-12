/**
 * ActivityIndicator — top-right rotating spinner.
 *
 * Shows while the avatar is loading, translating, or signing. Hidden otherwise.
 * Colour-matched to the app (paper + red accent). Respects prefers-reduced-motion.
 */
export class ActivityIndicator {
  private readonly root: HTMLDivElement;

  constructor(parent: HTMLElement) {
    this.root = document.createElement('div');
    this.root.className = 'activity';
    this.root.setAttribute('aria-hidden', 'true');
    this.root.dataset.active = 'false';

    const spinner = document.createElement('div');
    spinner.className = 'activity__spinner';
    this.root.append(spinner);

    parent.append(this.root);
  }

  /** Show the spinner. */
  show(): void {
    this.root.dataset.active = 'true';
  }

  /** Hide the spinner. */
  hide(): void {
    this.root.dataset.active = 'false';
  }

  /** Toggle by boolean. */
  setActive(active: boolean): void {
    this.root.dataset.active = active ? 'true' : 'false';
  }
}
