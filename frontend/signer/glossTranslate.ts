import { SIGN_LIBRARY, matchSigns, type SignMatch } from './SignLibrary';

/**
 * Turn typed English into a sequence of signs, preferring a real translation.
 *
 * matchSigns() is an exact string lookup over the surface forms written into
 * SignLibrary. It is fast and it is honest, but it only knows what was spelled
 * out for it: "thanked" misses THANK_YOU, "greetings" misses HELLO, and ISL
 * word order is not English word order at all. The backend can do better with
 * a model, so it gets asked first.
 *
 * The model never invents motion. It receives THIS page's vocabulary and picks
 * from it — the backend then discards any gloss that was not in the list it was
 * given, so the worst a bad completion can do is choose badly among signs that
 * genuinely exist.
 *
 * The fallback is the point of the design, not an afterthought. signer.html was
 * built to need no backend, and it still does not: no key, no server, a timeout
 * or a rubbish reply all end in the same place — matchSigns(), same as before.
 * A page that stopped signing because a language API was unreachable would be
 * worse than the page that existed before this file.
 */

const API = (() => {
  const override = new URLSearchParams(window.location.search).get('api');
  const configured = import.meta.env.VITE_API_URL as string | undefined;
  // Dev convenience only. On a phone 127.0.0.1 is the phone, so anything built
  // falls back to same-origin instead — see lecture/main.ts for the same trap.
  const fallback = import.meta.env.DEV ? 'http://127.0.0.1:8000' : '';
  return (override ?? configured ?? fallback).replace(/\/$/, '');
})();

/** Kept short: this sits between pressing Sign and the avatar moving. */
const TIMEOUT_MS = 9000;

export interface GlossResult {
  readonly matches: SignMatch[];
  /** Which route produced this, so the UI can say so rather than imply. */
  readonly source: 'llm' | 'matcher';
}

const BY_GLOSS = new Map(SIGN_LIBRARY.map((entry) => [entry.gloss, entry]));

export async function translateToSigns(text: string): Promise<GlossResult> {
  const fallback = (): GlossResult => ({ matches: matchSigns(text), source: 'matcher' });
  if (!text.trim()) return fallback();

  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    const response = await fetch(`${API}/gloss`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        // Send the vocabulary rather than letting the server keep its own copy.
        // Two lists would be two things to keep in step, and this one is the
        // one that actually maps to motion files.
        vocabulary: SIGN_LIBRARY.map((entry) => ({ gloss: entry.gloss, words: entry.words })),
      }),
      signal: controller.signal,
    }).finally(() => clearTimeout(timer));

    if (!response.ok) return fallback();
    const data = (await response.json()) as { glosses?: string[]; source?: string };
    if (data.source !== 'llm' || !Array.isArray(data.glosses)) return fallback();

    // Resolve glosses to the entries that own the motion. A gloss with no entry
    // is dropped rather than trusted — the backend already filters, so this is
    // the second of two independent checks on the same guarantee.
    const matches: SignMatch[] = [];
    for (const gloss of data.glosses) {
      const entry = BY_GLOSS.get(gloss);
      if (entry) matches.push({ entry, text: entry.words[0] });
    }

    // An empty result is a real answer — "nothing here is signable" — but it is
    // indistinguishable from a bad completion, and the matcher may still find
    // something. Preferring it costs nothing and cannot do worse.
    if (matches.length === 0) return fallback();
    return { matches, source: 'llm' };
  } catch {
    return fallback();
  }
}
