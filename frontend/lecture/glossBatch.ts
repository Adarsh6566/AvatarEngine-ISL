import { SIGN_LIBRARY, type SignMatch } from '../signer/SignLibrary';

/**
 * Upgrade a whole transcript's sign matches, in batches, in the background.
 *
 * The signer page translates one phrase when a button is pressed. A lecture is
 * a different problem: seventeen minutes of speech transcribes to 176 segments,
 * so four hours is roughly 2,500. Translating those one at a time at ~750ms
 * each would take half an hour before the avatar could sign anything.
 *
 * So this batches, and it runs AFTER the transcript is already usable. Rows are
 * built by the plain string matcher first — instantly, exactly as before — and
 * this walks the list improving them as answers arrive. Playback never waits on
 * a language model; if translation is slow, unavailable, or switched off, the
 * page behaves precisely as it did before this file existed.
 */

const API = (() => {
  const override = new URLSearchParams(window.location.search).get('api');
  const configured = import.meta.env.VITE_API_URL as string | undefined;
  const fallback = import.meta.env.DEV ? 'http://127.0.0.1:8000' : '';
  return (override ?? configured ?? fallback).replace(/\/$/, '');
})();

/**
 * Segments per request.
 *
 * Measured at 16: about 370ms per segment against ~750ms translating singly,
 * because the vocabulary listing dominates the prompt and is paid once per
 * batch rather than once per sentence. Larger batches amortise it further but
 * make each failure cost more, and give the model more room to lose track of
 * its own numbering.
 */
const BATCH_SIZE = 16;

/** Matches the server ceiling; a longer wait only delays giving up. */
const TIMEOUT_MS = 60_000;

const BY_GLOSS = new Map(SIGN_LIBRARY.map((e) => [e.gloss, e]));
const VOCABULARY = SIGN_LIBRARY.map((e) => ({ gloss: e.gloss, words: e.words }));

export interface BatchProgress {
  /** Segments translated so far, and the total to do. */
  done: number;
  total: number;
  /** Rows whose signs changed, cumulative — the visible benefit. */
  improved: number;
}

/**
 * Translate `texts`, calling `onBatch` with results as each batch lands.
 *
 * Indices are absolute into the original array, so the caller can update the
 * right rows without tracking batch boundaries. A batch that fails is skipped
 * rather than retried: its segments keep whatever the string matcher gave them,
 * which is the same outcome as translation being off.
 */
export async function translateTranscript(
  texts: readonly string[],
  onBatch: (from: number, matches: SignMatch[][]) => void,
  onProgress?: (progress: BatchProgress) => void,
  signal?: AbortSignal,
): Promise<void> {
  let improved = 0;

  for (let from = 0; from < texts.length; from += BATCH_SIZE) {
    if (signal?.aborted) return;
    const slice = texts.slice(from, from + BATCH_SIZE);

    let results: string[][] | null = null;
    try {
      const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
      const controller = new AbortController();
      // Abort if either the caller gives up or this batch runs long.
      signal?.addEventListener('abort', () => controller.abort(), { once: true });
      const response = await fetch(`${API}/gloss/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ texts: slice, vocabulary: VOCABULARY }),
        signal: controller.signal,
      }).finally(() => clearTimeout(timer));

      if (response.ok) {
        const data = (await response.json()) as { results?: string[][]; source?: string };
        if (data.source === 'llm' && Array.isArray(data.results)) results = data.results;
      }
    } catch {
      // Network error, timeout, abort — this batch simply keeps its matcher
      // results. Deliberately not retried: a lecture has thousands of segments
      // and a server that is down will not come back within one of them.
      results = null;
    }

    if (results) {
      const matches = results.map((glosses) =>
        glosses
          .map((g) => BY_GLOSS.get(g))
          .filter((e): e is NonNullable<typeof e> => Boolean(e))
          // The second of two independent checks that a gloss is real: the
          // server filters against the vocabulary it was sent, and this
          // resolves against the entries that actually own motion files.
          .map((entry) => ({ entry, text: entry.words[0] })),
      );
      improved += matches.filter((m) => m.length > 0).length;
      onBatch(from, matches);
    }

    onProgress?.({ done: Math.min(from + BATCH_SIZE, texts.length), total: texts.length, improved });
  }
}
