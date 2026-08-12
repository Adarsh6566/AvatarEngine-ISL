import json
import re
from dataclasses import dataclass
from pathlib import Path

try:
    from mapper import DEFAULT_GESTURE, MappedWord, map_recognition
except ImportError:  # when run as `backend.language.translator` from repo root
    from backend.mapper import DEFAULT_GESTURE, MappedWord, map_recognition  # type: ignore[no-redef]
from .recognizer import PhraseRecognizer, Recognition

_ALPHABET_PATH = Path(__file__).parent / "alphabet.json"


def _load_alphabet() -> dict[str, str]:
    try:
        with _ALPHABET_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("alphabet.json must be a dict")
        for k, v in data.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValueError(f"bad alphabet entry {k!r}: {v!r}")
        return data
    except Exception as exc:  # pragma: no cover — import-time resilience
        import logging

        logging.getLogger("avatar-engine").warning("alphabet load failed (%s) — using empty alphabet", exc)
        return {}


# The last-resort dictionary: one atomic gesture per character. Loaded once at
# import, and only ever consulted for words the word-level mapper could not
# resolve.
_ALPHABET: dict[str, str] = _load_alphabet()

# Splits a word into individual characters, discarding anything that is not a
# letter or digit (there should be none — the recogniser normalises first — but
# a stray character must never become a bogus gesture).
# Digits intentionally have no .vrma yet (P1-1 leave-as-is): spell() still
# emits "0"–"9" and Sequencer holds caption-only for them.
_CHARACTER = re.compile(r"[a-z0-9]")

recognizer = PhraseRecognizer()


def spell(word: str) -> list[str]:
    """
    Fingerspell one word: characters in, atomic gestures out.

    Mirrors the mapper's two-stage shape at character level:
      Stage 1 — pair every character with its gesture, in order, duplicates
                intact: "hello" -> [h:G_H] [e:G_E] [l:G_L] [l:G_L] [o:G_O]
      Stage 2 — bundle those into one ordered gesture list for the word.

    Lookups are done once per DISTINCT character, then replayed in order, so the
    repeated "l" in "hello" costs one lookup rather than two.

    Characters with no atomic gesture are dropped rather than emitted, so an
    unspellable symbol cannot inject a bogus token mid-word.
    """
    characters = _CHARACTER.findall(word)

    # Stage 1a: resolve the distinct characters only.
    resolved = {
        character: _ALPHABET.get(character)
        for character in set(characters)
    }

    # Stage 1b: replay in written order, duplicates intact.
    pairs = [
        MappedWord(word=character, gesture=resolved[character])
        for character in characters
        if resolved[character] is not None
    ]

    # Stage 2: bundle into a single ordered gesture list for this word.
    return [pair.gesture for pair in pairs]


@dataclass(frozen=True)
class Resolution:
    """
    How one word will be performed.

    `spelled` is recorded at the moment the decision is made rather than
    inferred later from the shape of `gestures` — a one-letter word spells to a
    single gesture, so length alone cannot tell the two cases apart.
    """

    gestures: list[str]
    spelled: bool


def resolve_vocabulary(recognition: Recognition) -> dict[str, Resolution]:
    """
    Resolve every distinct word to the gesture(s) that perform it.

    A mapped word yields a one-element list. An UNMAPPED word is fingerspelled
    instead, so it yields one gesture per character — the fallback that keeps
    the meaning rather than dropping the word.

    Uniform shape (always a list) is what lets both cases flow through the same
    replay step; the caller never branches on "was this fingerspelled".
    """
    mapping = map_recognition(recognition)

    return {
        word: (
            Resolution(gestures=spell(word), spelled=True)
            if gesture == DEFAULT_GESTURE
            else Resolution(gestures=[gesture], spelled=False)
        )
        for word, gesture in mapping.vocabulary.items()
    }


@dataclass(frozen=True)
class Segment:
    """
    One source word together with the gestures that perform it.

    Keeping the word attached is what lets the UI caption name the word being
    signed and — when `spelled` is true — highlight each letter as its gesture
    plays. A flat gesture list cannot express that: two adjacent spelled words
    would run together with no recoverable boundary.
    """

    word: str
    gestures: list[str]
    spelled: bool


def segment(text: str) -> list[Segment]:
    """
    Turn free text into per-word segments, in written order.

    Three passes, each doing strictly less work than the last:
      1. Recognise  — split into sentences and words, keep order and the set
      2. Resolve    — one lookup per DISTINCT word, fingerspelling the misses
      3. Replay     — expand the resolved gestures in written order
    """
    recognition = recognizer.split(text)
    resolved = resolve_vocabulary(recognition)

    return [
        Segment(
            word=word,
            gestures=resolved[word].gestures,
            spelled=resolved[word].spelled,
        )
        for word in recognition.words
    ]


def translate(text: str) -> list[str]:
    """
    Flat ordered gesture ids — the original contract, unchanged.

    Derived from segment() so the two can never disagree.
    """
    return [gesture for part in segment(text) for gesture in part.gestures]
