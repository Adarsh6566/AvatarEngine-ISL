/**
 * One source word paired with the gestures that perform it.
 *
 * This is the unit the backend sends and the unit the UI captions. The grouping
 * matters: a flat gesture list cannot say which word a run of LETTER_* gestures
 * belongs to, so "banana apple" would caption as one merged word.
 */
export interface SignSegment {
  /** The word as the user wrote it, normalised (e.g. "help"). */
  readonly word: string;
  /** Gesture ids in playback order. One entry if mapped, one per letter if spelled. */
  readonly gestures: readonly string[];
  /** True when the word had no sign and is being fingerspelled. */
  readonly spelled: boolean;
}
