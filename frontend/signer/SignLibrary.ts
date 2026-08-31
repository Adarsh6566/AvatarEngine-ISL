/**
 * SignLibrary — the new pipeline's dictionary: written text → captured motion.
 *
 * Deliberately standalone. This pipeline performs signs ONLY from skeleton
 * streams captured off real ISL video; it shares no vocabulary, manifest, or
 * backend with the .vrma app. Adding a sign is: extract the video with
 * pipeline/ (:8001), drop the JSON in public/skeleton/, add one entry here.
 */

export interface SignEntry {
  /** Gloss token, shown under the caption. */
  readonly gloss: string;
  /** Captured stream, served from public/. */
  readonly path: string;
  /** Written forms that select this sign. Phrases may contain spaces. */
  readonly words: readonly string[];
}

export const SIGN_LIBRARY: readonly SignEntry[] = [
  { gloss: 'HELLO',          path: '/skeleton/hello_captured.json',          words: ['hello', 'hi', 'hey'] },
  { gloss: 'ALRIGHT',        path: '/skeleton/alright.json',        words: ['alright', 'okay', 'ok'] },
  { gloss: 'GOOD_MORNING',   path: '/skeleton/good_morning.json',   words: ['good morning', 'morning'] },
  { gloss: 'GOOD_AFTERNOON', path: '/skeleton/good_afternoon.json', words: ['good afternoon', 'afternoon'] },
  { gloss: 'GOOD_EVENING',   path: '/skeleton/good_evening.json',   words: ['good evening', 'evening'] },
  { gloss: 'GOOD_NIGHT',     path: '/skeleton/good_night.json',     words: ['good night', 'night', 'goodnight'] },
  { gloss: 'HOW_ARE_YOU',    path: '/skeleton/how_are_you.json',    words: ['how are you', 'how are u', 'howdy'] },
  { gloss: 'THANK_YOU',      path: '/skeleton/thank_you.json',      words: ['thank you', 'thanks', 'thankyou', 'thank u'] },
  { gloss: 'PLEASED',        path: '/skeleton/pleased.json',        words: ['pleased', 'nice to meet you', 'glad'] },
];

/** One recognised sign in a sentence, with the text that selected it. */
export interface SignMatch {
  readonly entry: SignEntry;
  readonly text: string;
}

const LOOKUP: ReadonlyMap<string, SignEntry> = new Map(
  SIGN_LIBRARY.flatMap((entry) => entry.words.map((w) => [w, entry] as const)),
);

/** Longest phrase in the library, in words — bounds the match window. */
const LONGEST = Math.max(...[...LOOKUP.keys()].map((w) => w.split(' ').length));

/**
 * Split text into the signs that perform it, longest phrase first.
 *
 * "good morning" is ONE sign, not GOOD + MORNING, so phrases have to win over
 * their own first word. Unknown words are skipped rather than fingerspelled —
 * this pipeline has no letter clips, only captured signs.
 */
export function matchSigns(text: string): SignMatch[] {
  const words = text
    .toLowerCase()
    .replace(/[^\w\s]/g, ' ')
    .split(/\s+/)
    .filter(Boolean);

  const out: SignMatch[] = [];
  let i = 0;

  while (i < words.length) {
    let matched = false;
    for (let length = Math.min(LONGEST, words.length - i); length >= 1; length -= 1) {
      const phrase = words.slice(i, i + length).join(' ');
      const entry = LOOKUP.get(phrase);
      if (entry) {
        out.push({ entry, text: phrase });
        i += length;
        matched = true;
        break;
      }
    }
    if (!matched) i += 1;
  }

  return out;
}

/** Every written form the library understands, for the UI hint. */
export function knownPhrases(): string[] {
  return SIGN_LIBRARY.map((e) => e.words[0]);
}
