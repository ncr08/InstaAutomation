import io
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from instaautomation.covers import FfmpegCoverMaker
from instaautomation.ports import Reel

COVER_URL = "https://scontent.cdninstagram.com/v/DAbc123XyZ.jpg"


def reel(cover_url: str | None, video_path: Path = Path("/videos/DAbc123XyZ.mp4")) -> Reel:
    return Reel(url="https://www.instagram.com/reel/DAbc123XyZ/", shortcode="DAbc123XyZ", creator="", caption="", video_path=video_path, cover_url=cover_url)


class Recorder:
    """Stands in for the download and ffmpeg steps, writing a marker file for each."""

    def __init__(self, download_fails: bool = False) -> None:
        self.download_fails = download_fails
        self.calls: list[str] = []

    def download(self, url: str, out: Path) -> None:
        self.calls.append(f"download {url}")
        if self.download_fails:
            raise RuntimeError("403 URL signature expired")
        out.write_bytes(b"thumbnail")

    def extract_frame(self, video_path: Path, out: Path, at_seconds: float) -> None:
        self.calls.append(f"frame {video_path.name} at {at_seconds}")
        out.write_bytes(b"frame")

    def to_jpeg(self, image: Path, out: Path, width: int) -> None:
        out.write_bytes(b"jpeg of " + image.read_bytes() + f" at {width}".encode())

    def maker(self) -> FfmpegCoverMaker:
        return FfmpegCoverMaker(download=self.download, extract_frame=self.extract_frame, to_jpeg=self.to_jpeg)


def test_the_creators_cover_is_preferred_to_a_frame() -> None:
    recorder = Recorder()

    cover = recorder.maker().make(reel(COVER_URL))

    assert cover == b"jpeg of thumbnail at 480"
    assert recorder.calls == [f"download {COVER_URL}"]


def test_without_a_cover_a_frame_at_one_second_is_used() -> None:
    recorder = Recorder()

    cover = recorder.maker().make(reel(None))

    assert cover == b"jpeg of frame at 480"
    assert recorder.calls == ["frame DAbc123XyZ.mp4 at 1.0"]


def test_a_cover_that_fails_to_download_falls_back_to_a_frame() -> None:
    recorder = Recorder(download_fails=True)

    cover = recorder.maker().make(reel(COVER_URL))

    assert cover == b"jpeg of frame at 480"
    assert recorder.calls == [f"download {COVER_URL}", "frame DAbc123XyZ.mp4 at 1.0"]


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


@needs_ffmpeg
def test_a_frame_of_a_real_video_becomes_a_480_px_wide_jpeg(tmp_path: Path) -> None:
    video = tmp_path / "reel.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=c=teal:s=1080x1920:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
        check=True,
    )

    cover = FfmpegCoverMaker().make(reel(None, video))

    image = Image.open(io.BytesIO(cover))
    assert image.format == "JPEG"
    assert image.size == (480, 854)


@needs_ffmpeg
def test_a_video_shorter_than_a_second_still_gets_its_first_frame(tmp_path: Path) -> None:
    video = tmp_path / "blink.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=c=teal:s=720x1280:d=0.4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
        check=True,
    )

    cover = FfmpegCoverMaker().make(reel(None, video))

    assert Image.open(io.BytesIO(cover)).size == (480, 854)


@needs_ffmpeg
def test_a_downloaded_cover_is_resized_to_a_480_px_wide_jpeg(tmp_path: Path) -> None:
    def download(url: str, out: Path) -> None:
        Image.new("RGB", (1080, 1920), (200, 50, 50)).save(out, format="PNG")

    cover = FfmpegCoverMaker(download=download).make(reel(COVER_URL))

    image = Image.open(io.BytesIO(cover))
    assert image.format == "JPEG"
    assert image.size == (480, 854)
