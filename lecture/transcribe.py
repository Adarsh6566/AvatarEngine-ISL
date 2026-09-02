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

import os
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


# Handles from os.add_dll_directory must be kept alive: dropping one removes the
# directory from the search path again.
_DLL_DIRS: list = []
_REGISTERED: list[str] | None = None


def register_cuda_dlls() -> list[str]:
    """Put the pip-installed CUDA libraries where Windows will look for them.

    CTranslate2 needs CUDA 12 and cuDNN 9. Installing nvidia-cublas-cu12 and
    nvidia-cudnn-cu12 puts those DLLs under site-packages/nvidia/*/bin, which is
    on no search path at all — so without this the libraries are present and
    still "not found", which is a confusing way to fail.

    torch does the same thing for its own bundled libraries, which is why torch
    can report a working GPU while Whisper cannot load cublas.

    Returns the directories added, for logging. A no-op off Windows, where the
    loader follows RPATH and the wheels are built to suit.
    """
    global _REGISTERED
    if _REGISTERED or not hasattr(os, "add_dll_directory"):
        return _REGISTERED or []

    try:
        import nvidia

        # A PEP 420 namespace package: __file__ is None, and only __path__ says
        # where its parts live. Reading __file__ here silently found nothing.
        roots = [Path(p) for p in getattr(nvidia, "__path__", [])]
    except Exception:
        _REGISTERED = []
        return []

    added: list[str] = []
    for root in roots:
        for binary_dir in sorted(root.glob("*/bin")):
            path = str(binary_dir)
            try:
                _DLL_DIRS.append(os.add_dll_directory(path))
            except Exception:
                pass
            # add_dll_directory alone is not enough. It only affects loads that
            # opt into user directories, and CTranslate2 resolves cublas from
            # its own native code, which does not — so the directory is
            # registered and the library is still "not found". PATH is consulted
            # by the ordinary search order that such loads do use, and it has to
            # be set BEFORE ctranslate2 is imported, which is why this runs
            # before the model is constructed rather than at module import.
            if path not in os.environ.get("PATH", ""):
                os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")
            added.append(path)
    _REGISTERED = added
    return added


def _load(model_size: str, device: str, compute_type: str):
    """Models are cached: loading costs seconds, and a lecture is many requests."""
    if device.startswith("cuda"):
        register_cuda_dlls()
    key = (model_size, device, compute_type)
    if key not in _MODELS:
        from faster_whisper import WhisperModel

        _MODELS[key] = WhisperModel(model_size, device=device, compute_type=compute_type)
    return _MODELS[key]


# Set once a CUDA attempt has failed, so the fallback is not re-attempted on
# every request. Whisper runs through CTranslate2, which is a separate CUDA
# build from torch's — torch reporting a working GPU says nothing about whether
# CTranslate2 can use it.
_CUDA_UNAVAILABLE_REASON: str | None = None


def _looks_like_missing_cuda(error: Exception) -> bool:
    """Is this the CUDA runtime being absent rather than a real failure?

    CTranslate2 wants CUDA 12 and cuDNN 9 and reports their absence as a missing
    DLL at the first encode, not at load — so this is caught around the
    transcription, not around the constructor.
    """
    text = str(error).lower()
    return any(
        s in text
        for s in ("cublas", "cudnn", "cuda", "libcu", "no kernel image", "cannot be loaded")
    )


def pick_device() -> tuple[str, str]:
    """(device, compute_type) — CUDA with float16 when available, else int8 on CPU.

    int8 is the reason this is usable without a GPU: it runs several times
    faster than float32 on CPU for a small accuracy cost that clear speech
    absorbs easily.

    A CUDA attempt that has already failed is not repeated. torch having a
    working GPU is NOT sufficient here: Whisper runs through CTranslate2, which
    carries its own CUDA build, and the two can disagree — a CUDA 13 torch
    alongside a CTranslate2 wanting CUDA 12 leaves torch reporting success while
    Whisper cannot load cublas at all.
    """
    if _CUDA_UNAVAILABLE_REASON is not None:
        return "cpu", "int8"
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
    global _CUDA_UNAVAILABLE_REASON

    device, compute_type = pick_device()

    def run(dev: str, ctype: str):
        model = _load(model_size, dev, ctype)
        return model.transcribe(  # type: ignore[attr-defined]
            str(video_path),
            language=language,
            vad_filter=vad,
            beam_size=5,
        )

    try:
        segments_iter, info = run(device, compute_type)
    except Exception as e:
        # A GPU that cannot actually run Whisper must not take the transcript
        # down with it. Falling back keeps the pipeline working on any machine,
        # which matters more here than the speed the GPU would have added.
        if device == "cpu" or not _looks_like_missing_cuda(e):
            raise
        _CUDA_UNAVAILABLE_REASON = str(e)
        print(f"[transcribe] GPU unusable, falling back to CPU: {e}")
        device, compute_type = "cpu", "int8"
        segments_iter, info = run(device, compute_type)

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
