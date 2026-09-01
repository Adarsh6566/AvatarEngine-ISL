/**
 * SpeechInput — spoken words in, the same text the input box would have given.
 *
 * Wraps the browser's SpeechRecognition so the signer can be driven by voice
 * without gaining a backend: recognition runs in the browser, and the page
 * still loads from static files alone. That matters for this app specifically,
 * since it is the one pipeline that needs no server.
 *
 * Recognition is CONTINUOUS. A lecture is not one utterance, and the eventual
 * use — a speaker talking while the avatar signs along — is a stream of them,
 * so the recogniser stays open and reports each phrase as it settles rather
 * than stopping after the first.
 *
 * Two kinds of result arrive. Interim text changes as the recogniser revises
 * its guess and is only worth showing; final text is settled and is what should
 * be signed. Acting on interim text would sign words that are about to be
 * retracted.
 */

/**
 * The part of the Web Speech API this file uses.
 *
 * TypeScript's DOM lib ships the event types but not the recogniser interface,
 * because the API is still non-standard. Declaring only what is used keeps the
 * gap small and honest, rather than pulling in a definition for a shape the
 * browser may not match.
 */
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
}

export interface SpeechInputHandlers {
  /** Best guess so far — shown, never signed. */
  readonly onInterim?: (text: string) => void;
  /** Settled phrase, ready to sign. */
  readonly onFinal: (text: string) => void;
  /** Listening started or stopped, for the button's state. */
  readonly onStateChange?: (listening: boolean) => void;
  /** Something the user needs to know: no microphone permission, no speech. */
  readonly onError?: (message: string) => void;
}

/** The constructor, under whichever name this browser publishes it. */
function recognitionCtor(): (new () => SpeechRecognitionLike) | null {
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function isSpeechSupported(): boolean {
  return recognitionCtor() !== null;
}

/** What went wrong, in words a user can act on. */
function describe(error: string): string {
  switch (error) {
    case 'not-allowed':
    case 'service-not-allowed':
      return 'Microphone blocked — allow access in the address bar, then try again.';
    case 'no-speech':
      return 'Did not catch that.';
    case 'audio-capture':
      return 'No microphone found.';
    case 'network':
      return 'Speech recognition needs a network connection.';
    default:
      return `Speech recognition failed (${error}).`;
  }
}

export class SpeechInput {
  private readonly handlers: SpeechInputHandlers;
  private recognition: SpeechRecognitionLike | null = null;
  /** What the user asked for, as opposed to whether the engine is up. */
  private wanted = false;

  constructor(handlers: SpeechInputHandlers, lang = 'en-IN') {
    this.handlers = handlers;
    const Ctor = recognitionCtor();
    if (!Ctor) return;

    const recognition = new Ctor();
    recognition.lang = lang;
    recognition.continuous = true;
    recognition.interimResults = true;

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let interim = '';
      // Only results from resultIndex on are new; earlier ones were already
      // reported and re-reading them would sign the same phrase twice.
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const text = result[0]?.transcript?.trim() ?? '';
        if (!text) continue;
        if (result.isFinal) this.handlers.onFinal(text);
        else interim += `${text} `;
      }
      if (interim) this.handlers.onInterim?.(interim.trim());
    };

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      // 'no-speech' and 'aborted' are ordinary in a continuous session — a
      // pause between sentences raises them — so they must not stop listening.
      if (event.error === 'no-speech' || event.error === 'aborted') return;
      this.handlers.onError?.(describe(event.error));
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
        this.wanted = false;
        this.handlers.onStateChange?.(false);
      }
    };

    // Browsers end a continuous session on their own after a silence. Restart
    // while the user still wants to listen, so a pause does not silently drop
    // the microphone mid-lecture.
    recognition.onend = () => {
      if (!this.wanted) {
        this.handlers.onStateChange?.(false);
        return;
      }
      try {
        recognition.start();
      } catch {
        this.wanted = false;
        this.handlers.onStateChange?.(false);
      }
    };

    this.recognition = recognition;
  }

  get listening(): boolean {
    return this.wanted;
  }

  start(): void {
    if (!this.recognition || this.wanted) return;
    this.wanted = true;
    try {
      this.recognition.start();
      this.handlers.onStateChange?.(true);
    } catch (error) {
      this.wanted = false;
      this.handlers.onStateChange?.(false);
      this.handlers.onError?.(String(error));
    }
  }

  stop(): void {
    if (!this.recognition || !this.wanted) return;
    this.wanted = false;
    this.recognition.stop();
    this.handlers.onStateChange?.(false);
  }

  toggle(): void {
    if (this.wanted) this.stop();
    else this.start();
  }
}
