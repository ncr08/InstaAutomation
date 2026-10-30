"""CoverMaker adapter: the creator's cover image, or failing that a frame of the video, as a small JPEG."""

import logging
import tempfile
from collections.abc import Callable
from pathlib import Path

import httpx

from instaautomation import media
from instaautomation.ports import Reel

# Tens of KB per entry: big enough for a card and the entry page, small enough to commit.
COVER_WIDTH = 480
FRAME_AT_SECONDS = 1.0

Download = Callable[[str, Path], None]
FrameExtractor = Callable[[Path, Path, float], None]
JpegConverter = Callable[[Path, Path, int], None]

log = logging.getLogger(__name__)


class FfmpegCoverMaker:
    def __init__(
        self,
        download: Download | None = None,
        extract_frame: FrameExtractor | None = None,
        to_jpeg: JpegConverter | None = None,
    ) -> None:
        self._download = download or _download
        self._extract_frame = extract_frame or media.extract_frame
        self._to_jpeg = to_jpeg or media.to_jpeg

    def make(self, reel: Reel) -> bytes:
        with tempfile.TemporaryDirectory(prefix="cover-") as work_dir:
            work = Path(work_dir)
            source = self._cover_image(reel, work) or self._frame(reel, work)
            out = work / "cover.jpg"
            self._to_jpeg(source, out, COVER_WIDTH)
            return out.read_bytes()

    def _cover_image(self, reel: Reel, work: Path) -> Path | None:
        if not reel.cover_url:
            return None
        image = work / "cover-source"
        try:
            self._download(reel.cover_url, image)
        except Exception:
            log.warning("could not download the cover of %s, using a frame instead", reel.shortcode, exc_info=True)
            return None
        return image

    def _frame(self, reel: Reel, work: Path) -> Path:
        frame = work / "frame.png"
        self._extract_frame(reel.video_path, frame, FRAME_AT_SECONDS)
        return frame


def _download(url: str, out: Path) -> None:
    response = httpx.get(url, timeout=30, follow_redirects=True)
    response.raise_for_status()
    out.write_bytes(response.content)
