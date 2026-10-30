"""ScreenReader adapter: samples frames with ffmpeg and reads their text with tesseract."""

import re
import tempfile
from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path

from instaautomation import media

FrameSampler = Callable[[Path, Path, float], list[Path]]
Ocr = Callable[[Path], str]

# Two lines this alike are the same on-screen text read through different OCR noise.
SAME_TEXT = 0.85
# Shorter lines are OCR noise from edges and backgrounds, not text someone put on screen.
MIN_CHARACTERS = 2


class OcrScreenReader:
    def __init__(self, every_seconds: float = 2, sample_frames: FrameSampler | None = None, ocr: Ocr | None = None) -> None:
        self._every_seconds = every_seconds
        self._sample_frames = sample_frames or media.sample_frames
        self._ocr = ocr or media.ocr

    def read(self, video_path: Path) -> str:
        with tempfile.TemporaryDirectory(prefix="frames-") as work_dir:
            frames = self._sample_frames(video_path, Path(work_dir), self._every_seconds)
            texts = [self._ocr(frame) for frame in frames]
        kept: list[str] = []
        for text in texts:
            for line in text.splitlines():
                _keep(kept, " ".join(line.split()))
        return "\n".join(kept)


def _keep(kept: list[str], line: str) -> None:
    """Adds a line unless it's already on the list, keeping lines in the order they first appeared."""
    new = _normalised(line)
    if len(new.replace(" ", "")) < MIN_CHARACTERS:
        return
    for i, seen in enumerate(kept):
        old = _normalised(seen)
        if f" {new} " in f" {old} " or old.startswith(new) or _same_text(line, seen):
            return
        if new.startswith(old):
            # Text being typed out: the fuller version replaces the fragment, in the fragment's place.
            kept[i] = line
            return
    kept.append(line)


def _normalised(line: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", line.lower()).strip()


def _same_text(a: str, b: str) -> bool:
    return SequenceMatcher(None, _normalised(a), _normalised(b)).ratio() >= SAME_TEXT
