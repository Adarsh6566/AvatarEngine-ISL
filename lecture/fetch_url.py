"""Fetch a lecture from a URL so it can be transcribed like an uploaded file.

Finding recordings with a clearly framed lecturer is the practical bottleneck in
testing this pipeline, and most of what exists is streamed rather than offered
as a download. yt-dlp closes that gap for any site it supports.

It also reports what it fetched, which matters more here than usual. This
pipeline's whole purpose is to reuse a person's likeness, so who the speaker is
and under what licence their recording was published are not incidental
metadata — they are the terms under which the output may be used at all. The
licence is passed through to the caller rather than quietly discarded.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FetchedVideo:
    path: Path
    title: str
    duration: float
    uploader: str
    license: str | None
    webpage_url: str
    extractor: str

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "duration": round(self.duration, 2),
            "uploader": self.uploader,
            "license": self.license,
            "webpage_url": self.webpage_url,
            "source": self.extractor,
        }


class FetchError(RuntimeError):
    pass


def fetch(url: str, dest_dir: Path, max_height: int = 720, max_duration: float = 3600.0) -> FetchedVideo:
    """Download `url` into `dest_dir` and describe what came back.

    Capped at 720p: the pipeline needs audio plus a frame clear enough to find a
    person, and a 4K download would cost minutes and gigabytes to produce
    exactly the same transcript.

    `max_duration` is a guard, not a preference. Whisper is roughly a tenth of
    real time, so an unnoticed three-hour stream would sit transcribing for
    twenty minutes with nothing to show; better to refuse it and say why.
    """
    try:
        from yt_dlp import YoutubeDL
    except ImportError as e:  # pragma: no cover
        raise FetchError("yt-dlp is not installed (pip install yt-dlp)") from e

    dest_dir.mkdir(parents=True, exist_ok=True)

    options = {
        "format": f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best",
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
    }

    with YoutubeDL(options) as ydl:
        try:
            # Probe first so an over-long video is refused before it is fetched,
            # not after.
            info = ydl.extract_info(url, download=False)
        except Exception as e:
            raise FetchError(f"could not read {url}: {e}") from e

        if info is None:
            raise FetchError(f"nothing found at {url}")
        if info.get("_type") == "playlist":
            raise FetchError("that URL is a playlist; give a single video")

        duration = float(info.get("duration") or 0.0)
        if duration > max_duration:
            raise FetchError(
                f"video is {duration / 60:.0f} minutes, over the {max_duration / 60:.0f} minute limit"
            )

        try:
            info = ydl.extract_info(url, download=True)
        except Exception as e:
            raise FetchError(f"download failed: {e}") from e

        path = Path(ydl.prepare_filename(info))
        if not path.exists():
            # Merging video and audio can change the extension from what the
            # template predicted.
            candidates = sorted(dest_dir.glob(f"{info.get('id', '*')}.*"))
            if not candidates:
                raise FetchError("download reported success but produced no file")
            path = candidates[0]

    return FetchedVideo(
        path=path,
        title=info.get("title") or path.stem,
        duration=float(info.get("duration") or 0.0),
        uploader=info.get("uploader") or info.get("channel") or "unknown",
        license=info.get("license"),
        webpage_url=info.get("webpage_url") or url,
        extractor=info.get("extractor_key") or "unknown",
    )
