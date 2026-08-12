import type { SignSegment } from '../sign/SignSegment';

/**
 * SignCaption — the red banner at the top of the screen naming the word the
 * avatar is currently signing.
 *
 * Two modes, decided by the segment:
 *   mapped   — the word is shown whole, with its gesture id underneath
 *   spelled  — the word is broken into letters, and each lights up as its
 *              gesture plays, so the viewer can follow the fingerspelling
 *
 * It renders and nothing else. It does not know about the avatar, the
 * sequencer's timing, or where segments come from — it is handed a segment and
 * an index, and draws that.
 */
export class SignCaption {
  private readonly root: HTMLDivElement;
  private readonly word: HTMLDivElement;
  private readonly meta: HTMLDivElement;

  /** One span per letter, in order, while a spelled word is on screen. */
  private letters: HTMLSpanElement[] = [];
  private segment: SignSegment | null = null;

  constructor(parent: HTMLElement) {
    this.root = document.createElement('div');
    this.root.className = 'caption';
    this.root.dataset.state = 'idle';

    const box = document.createElement('div');
    box.className = 'caption__box';

    this.word = document.createElement('div');
    this.word.className = 'caption__word';

    this.meta = document.createElement('div');
    this.meta.className = 'caption__meta';

    box.append(this.word, this.meta);
    this.root.append(box);
    parent.append(this.root);
  }

  /**
   * Show a new word. Rebuilds the letter spans only when the word is spelled —
   * a mapped word is a single run of text with nothing to highlight.
   */
  showSegment(segment: SignSegment): void {
    this.segment = segment;
    this.root.dataset.state = 'active';
    this.root.dataset.mode = segment.spelled ? 'spelled' : 'mapped';

    this.word.replaceChildren();
    this.letters = [];

    if (segment.spelled) {
      for (const character of segment.word) {
        const span = document.createElement('span');
        span.className = 'caption__letter';
        span.textContent = character;
        this.letters.push(span);
        this.word.append(span);
      }
      this.meta.textContent = 'spelling';
    } else {
      this.word.textContent = segment.word;
      this.meta.textContent = segment.gestures[0] ?? '';
    }
  }

  /**
   * Advance the highlight to gesture `index` of the current word.
   *
   * No-op for mapped words — there is a single gesture and the whole word is
   * already lit. Bounds-checked because a character with no atomic gesture is
   * dropped upstream, which would make gestures shorter than the word.
   */
  highlight(index: number): void {
    if (!this.segment?.spelled) return;

    this.letters.forEach((span, position) => {
      span.classList.toggle('is-active', position === index);
      span.classList.toggle('is-done', position < index);
    });

    const gestureId = this.segment.gestures[index];
    if (gestureId) this.meta.textContent = gestureId.replace(/^(LETTER|DIGIT)_/, '');
  }

  /** Fade the banner out. Content is left in place so the exit does not flicker. */
  clear(): void {
    this.segment = null;
    this.root.dataset.state = 'idle';
  }
}
