import json
from dataclasses import dataclass
from pathlib import Path

try:
    from language.recognizer import Recognition
except ImportError:  # when run as `backend.mapper` from repo root
    from backend.language.recognizer import Recognition  # type: ignore[no-redef]

def _vocabulary_path() -> Path:
    # Config-driven path — file is a generated artifact, not hardcode (A)
    try:
        try:
            from config import get_dictionary_path
        except ImportError:
            from backend.config import get_dictionary_path  # type: ignore[no-redef]

        p = Path(get_dictionary_path())
        # Allow relative to repo root or backend/
        if not p.is_absolute():
            # Try repo root first, then backend dir
            for base in [Path(__file__).parent.parent, Path(__file__).parent]:
                cand = base / p
                if cand.exists():
                    return cand
            # Fallback to repo-root relative
            return Path(__file__).parent.parent / p
        return p
    except Exception:
        return Path(__file__).parent / "vocabulary.json"


_VOCABULARY_PATH = _vocabulary_path()


def _load_vocabulary(path: Path | None = None) -> dict[str, str]:
    p = path or _VOCABULARY_PATH
    try:
        with p.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("vocabulary.json must be a dict")
        for k, v in data.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValueError(f"bad entry {k!r}: {v!r}")
            if k != k.lower():
                raise ValueError(f"vocabulary key must be lowercase: {k!r}")
        return data
    except Exception as exc:  # pragma: no cover — import-time resilience
        import logging

        logging.getLogger("avatar-engine").warning("vocabulary load failed %s (%s) — using empty vocab", p, exc)
        return {}


# Loaded once at import. Every mapping call reads this dict, never the disk.
# Generated artifact — offline pipeline writes public/animations/*.vrma + vocabulary.json fragment.
_VOCABULARY: dict[str, str] = _load_vocabulary()


def reload_vocabulary() -> int:
    """Hot-reload vocab from disk (config path). Returns entry count. Called by /admin/reload-vocab or /ready probe."""
    global _VOCABULARY, _VOCABULARY_PATH
    _VOCABULARY_PATH = _vocabulary_path()
    data = _load_vocabulary()
    _VOCABULARY = data
    return len(data)

# Returned for words that have no sign. Deliberately NOT "UNKNOWN": that value
# means "the translator could not understand this", whereas this means "the word
# was understood, we simply have no gesture for it". Downstream can skip these
# silently instead of surfacing them as failures.
DEFAULT_GESTURE = "UNMAPPED"


@dataclass(frozen=True)
class MappedWord:
    """One word paired with the gesture it resolved to."""

    word: str
    gesture: str


@dataclass(frozen=True)
class Mapping:
    """
    Both views of a mapped input.

    vocabulary — distinct word -> gesture. One entry per unique word, so a dict
                 is the natural shape: keys cannot repeat.
    sequence   — every word in written order, duplicates intact. A dict CANNOT
                 hold this (repeated words would collapse into one key), so it
                 is a list of pairs.
    """

    vocabulary: dict[str, str]
    sequence: list[MappedWord]


def map_vocabulary(recognition: Recognition) -> dict[str, str]:
    """
    Resolve the distinct words only — one lookup per unique word.

    This is the expensive pass, and it is bounded by vocabulary size rather than
    input length: a paragraph saying "please" fifty times costs one lookup.
    """
    return {
        word: _VOCABULARY.get(word, DEFAULT_GESTURE)
        for word in recognition.vocabulary
    }


def map_sequence(
    recognition: Recognition,
    vocabulary: dict[str, str] | None = None,
) -> list[MappedWord]:
    """
    Pair every word with its gesture, in written order, duplicates included.

    Does no lookups of its own — it replays the vocabulary pass, which is the
    whole point: resolution happens once per distinct word, and this arranges
    those results into the order the sentence needs.
    """
    resolved = vocabulary if vocabulary is not None else map_vocabulary(recognition)

    return [
        MappedWord(word=word, gesture=resolved[word])
        for word in recognition.words
    ]


def map_recognition(recognition: Recognition) -> Mapping:
    """Map once, return both views. The normal entry point."""
    vocabulary = map_vocabulary(recognition)
    return Mapping(
        vocabulary=vocabulary,
        sequence=map_sequence(recognition, vocabulary),
    )


def to_gloss(mapping: Mapping, include_unmapped: bool = False) -> list[str]:
    """
    Flatten a Mapping down to the ordered gesture ids the frontend plays.

    Words with no sign are dropped by default, so one unmappable word no longer
    injects a bogus token into the middle of a sentence.
    """
    return [
        pair.gesture
        for pair in mapping.sequence
        if include_unmapped or pair.gesture != DEFAULT_GESTURE
    ]


def map_gloss(gloss: list[str]) -> list[str]:
    """
    Deprecated legacy passthrough — superseded by map_recognition().
    Emits DeprecationWarning and returns input unchanged.
    """
    import warnings

    warnings.warn("map_gloss is deprecated — use map_recognition()", DeprecationWarning, stacklevel=2)
    return gloss
