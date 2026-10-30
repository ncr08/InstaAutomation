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
SAME_TEXT_RATIO = 0.85
# Shorter lines are OCR noise from edges and backgrounds, not text someone put on screen.
MIN_CHARACTERS = 2


class OcrScreenReader:
    def __init__(
        self,
        every_seconds: float = 2,
        sample_frames: FrameSampler | None = None,
        ocr: Ocr | None = None,
    ) -> None:
        self._every_seconds = every_seconds
        self._sample_frames = sample_frames or media.sample_frames
        self._ocr = ocr or media.ocr

    def read(self, video_path: Path) -> str:
        with tempfile.TemporaryDirectory(prefix="frames-") as work_dir:
            frames = self._sample_frames(video_path, Path(work_dir), self._every_seconds)
            texts = [self._ocr(frame) for frame in frames]
        kept: list[str] = []
        for text in texts:
            lines = [" ".join(line.split()) for line in text.splitlines()]
            on_screen = {_comparable(line) for line in lines}
            for line in lines:
                _keep(kept, line, on_screen)
        return "\n".join(kept)


def _keep(kept: list[str], line: str, on_screen: set[str]) -> None:
    """Adds a line unless it's already on the list, keeping lines in the order they first appeared."""
    new = _comparable(line)
    if len(new.replace(" ", "")) < MIN_CHARACTERS:
        return
    for i, seen in enumerate(kept):
        old = _comparable(seen)
        if _same_text(new, old) or old.startswith(f"{new} "):
            return
        if new.startswith(old) and old not in on_screen:
            # Text being typed out: the fragment is gone from the screen, so the fuller version
            # replaces it in its place. A shorter line still on screen (Step 1, Step 12) is its own line.
            kept[i] = line
            return
    kept.append(line)


def _comparable(line: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", line.lower()).strip()


def _same_text(a: str, b: str) -> bool:
    # Numbers (step 1 vs step 12, version 3 vs 4) carry meaning that a similarity ratio would wave through.
    return re.findall(r"\d+", a) == re.findall(r"\d+", b) and SequenceMatcher(None, a, b).ratio() >= SAME_TEXT_RATIO
