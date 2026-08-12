/**
 * SignControls — the input bar: a text field, a Sign button, and a status line.
 *
 * It knows nothing about the avatar, the translator, or Three.js. It collects a
 * phrase and reports status; the composition root wires its `onSign` callback to
 * the rest of the pipeline, keeping UI and logic decoupled.
 */
export interface SignControlsOptions {
  /** Called with the raw input text when the user submits (button or Enter). */
  onSign: (text: string) => void;
}

import { APP_CONFIG } from "../config/appConfig";

export class SignControls {
  private readonly input: HTMLInputElement;
  private readonly button: HTMLButtonElement;
  private readonly message: HTMLParagraphElement;

  constructor(parent: HTMLElement, options: SignControlsOptions) {
    const root = document.createElement('div');
    root.className = 'bar';

    const field = document.createElement('div');
    field.className = 'bar__field';

    this.input = document.createElement('input');
    this.input.type = 'text';
    this.input.className = 'bar__input';
    this.input.placeholder = 'Say something…';
    this.input.autocomplete = 'off';
    this.input.spellcheck = false;
    this.input.maxLength = APP_CONFIG.validationMax;
    this.input.setAttribute('aria-label', 'Text to sign');
    this.input.setAttribute('maxlength', String(APP_CONFIG.validationMax));

    this.button = document.createElement('button');
    this.button.type = 'button';
    this.button.className = 'bar__button';
    this.button.textContent = 'Sign';

    this.message = document.createElement('p');
    this.message.className = 'bar__message';
    this.message.setAttribute('role', 'status');

    field.append(this.input, this.button);
    root.append(field, this.message);
    parent.append(root);

    const submit = (): void => {
      const text = this.input.value.trim();
      if (text.length > 0) options.onSign(text);
    };

    this.button.addEventListener('click', submit);
    this.input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') submit();
    });
  }

  /** Show a status line under the input. */
  showMessage(text: string): void {
    this.message.textContent = text;
  }

  /** Enable or disable the controls (while loading, or during playback). */
  setEnabled(enabled: boolean): void {
    this.input.disabled = !enabled;
    this.button.disabled = !enabled;
  }

  /** Move focus to the input — called once the avatar is ready. */
  focus(): void {
    this.input.focus();
  }
}
