"""Speech in a video to timed text.

Timing is the whole point. Signing a lecture is not translating a document: each
phrase has to be performed while the lecturer is saying it, so the transcript
must carry when each segment starts and ends, not just what was said.

Whisper runs locally through faster-whisper. That keeps a lecture recording —
which may be a real classroom, with real students audible — on the machine that
holds it, and it decodes the video's audio itself, so no ffmpeg binary has to be
found on PATH.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

# Small enough to run on CPU at faster than real time, large enough to be
# usable on clear lecture audio. Bigger models are a config change, not a
# rewrite — see transcribe(model_size=...).
DEFAULT_MODEL = "base"

_MODELS: dict[tuple[str, str, str], object] = {}


@dataclass(frozen=True)
class Segment:
    """One spoken phrase, with the window it occupies in the video."""

    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return max(self.end - self.start, 0.0)


@dataclass(frozen=True)
class Transcript:
    language: str
    language_probability: float
    duration: float
    model: str
    segments: list[Segment]

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "language_probability": round(self.language_probability, 3),
            "duration": round(self.duration, 2),
            "model": self.model,
            "segments": [
                {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text}
                for s in self.segments
            ],
        }


def _load(model_size: str, device: str, compute_type: str):
    """Models are cached: loading costs seconds, and a lecture is many requests."""
    key = (model_size, device, compute_type)
    if key not in _MODELS:
        from faster_whisper import WhisperModel

        _MODELS[key] = WhisperModel(model_size, device=device, compute_type=compute_type)
    return _MODELS[key]


def pick_device() -> tuple[str, str]:
    """(device, compute_type) — CUDA with float16 when available, else int8 on CPU.

    int8 is the reason this is usable without a GPU: it runs several times
    faster than float32 on CPU for a small accuracy cost that clear speech
    absorbs easily.
    """
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def transcribe(
    video_path: Path,
    model_size: str = DEFAULT_MODEL,
    language: str | None = None,
    vad: bool = True,
) -> Transcript:
    """Transcribe a video's audio into timed segments.

    `language=None` lets Whisper detect it, which is right for an unknown
    upload; pinning it is faster and more accurate when you already know.

    Voice-activity detection is on by default: lecture recordings are mostly
    silence and room noise between sentences, and without it Whisper narrates
    that silence — inventing text where nobody spoke.
    """
    device, compute_type = pick_device()
    model = _load(model_size, device, compute_type)

    segments_iter, info = model.transcribe(  # type: ignore[attr-defined]
        str(video_path),
        language=language,
        vad_filter=vad,
        beam_size=5,
    )

    segments = [
        Segment(start=float(s.start), end=float(s.end), text=s.text.strip())
        for s in segments_iter
        if s.text and s.text.strip()
    ]

    return Transcript(
        language=info.language,
        language_probability=float(info.language_probability),
        duration=float(info.duration),
        model=f"{model_size} ({device}/{compute_type})",
        segments=segments,
    )
