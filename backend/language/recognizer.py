import re
from dataclasses import dataclass

from .normalizer import TextNormalizer

# Split levels, applied top-down by _split_recursive.
#   Level 0: paragraph -> sentences, on terminal punctuation and newlines.
#   Level 1: sentence  -> words, on any run of whitespace.
# Adding a level (e.g. clauses on commas) means adding one splitter here; the
# recursion itself never changes.
_SENTENCE_BOUNDARY = re.compile(r"[.!?\n]+")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Recognition:
    """
    The full result of recognising one input.

    Three views of the same text, all derived in a single pass:
      sentences  — words grouped by sentence, structure preserved
      words      — every word, flattened, IN THE ORDER IT WAS WRITTEN
      vocabulary — the distinct words, unordered

    `words` is what drives playback order. `vocabulary` is what the mapper
    resolves, so each distinct word costs one lookup no matter how often it
    appears. Immutable, so it is safe to hold across requests.
    """

    sentences: tuple[tuple[str, ...], ...]
    words: tuple[str, ...]
    vocabulary: frozenset[str]


class PhraseRecognizer:
    """
    Splits free text into ordered words and a distinct-word set.

    Runs on RAW text, not normalised text: TextNormalizer strips punctuation,
    which would destroy the sentence boundaries this class splits on. Each word
    is normalised individually AFTER splitting instead.

    Order and uniqueness are produced together and kept together — the ordered
    words stay here (see `last()`), and the vocabulary set is handed to the
    mapper for resolution.
    """

    def __init__(self, normalizer: TextNormalizer | None = None) -> None:
        self._normalizer = normalizer or TextNormalizer()
        self._last: Recognition | None = None

    def recognize(self, text: str) -> set[str]:
        """
        Deprecated — use split(). Stores state on the singleton, so concurrent
        requests can clobber each other. Kept only for backward compat.
        """
        import warnings

        warnings.warn("recognize()/last() is deprecated — use split()", DeprecationWarning, stacklevel=2)
        recognition = self.split(text)
        self._last = recognition
        return set(recognition.vocabulary)

    def split(self, text: str) -> Recognition:
        """Split `text` into all three views. Pure — no state is touched."""
        nested = self._split_recursive(text, level=0)

        sentences = tuple(
            tuple(sentence) for sentence in nested if sentence
        )
        words = tuple(word for sentence in sentences for word in sentence)

        return Recognition(
            sentences=sentences,
            words=words,
            vocabulary=frozenset(words),
        )

    def last(self) -> Recognition | None:
        """Deprecated — use the Recognition returned by split() directly."""
        import warnings

        warnings.warn("last() is deprecated — use split() return value", DeprecationWarning, stacklevel=2)
        return self._last

    def _split_recursive(self, text: str, level: int) -> list:
        """
        Descend the split levels, one delimiter per level.

        Each level cuts the text it is given and recurses on every piece, so the
        depth of the returned structure equals the number of levels: level 0
        yields sentences, each of which yields words. The base case normalises
        the leaf and hands back a bare word.
        """
        if level == len(self._LEVELS):
            return self._normalizer.normalize(text)

        pattern = self._LEVELS[level]
        pieces = (piece for piece in pattern.split(text) if piece.strip())

        return [
            leaf
            for leaf in (self._split_recursive(piece, level + 1) for piece in pieces)
            if leaf  # drop words that normalise away to nothing (e.g. "--")
        ]

    _LEVELS = (_SENTENCE_BOUNDARY, _WHITESPACE)
