"""Short sample reels with known speech and on-screen text, for the media smoke tests (macOS: uses `say`)."""

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import pytest
from PIL import Image, ImageDraw, ImageFont

Audio = Literal["speech", "silence", "none"]

SPEECH = "Open your settings file and add the allowlist."
# (text on screen, seconds shown): a held caption, then a command typed out over two frames.
SCREENS = [
    ("Stop clicking approve", 4.0),
    ("claude --permission", 2.0),
    ("claude --permission-mode plan", 4.0),
]


@pytest.fixture
def sample_reel(tmp_path: Path) -> Callable[[Audio], Path]:
    return lambda audio: build_sample_reel(tmp_path, audio)


def build_sample_reel(out_dir: Path, audio: Audio) -> Path:
    """A 10-second reel; `audio` is "speech", "silence" (a silent track) or "none" (no audio track)."""
    concat = out_dir / "frames.txt"
    entries = []
    for i, (text, seconds) in enumerate(SCREENS):
        frame = out_dir / f"screen-{i}.png"
        _draw(text, frame)
        entries.append(f"file '{frame}'\nduration {seconds}")
    # The concat demuxer ignores the last duration unless the last file is listed again.
    entries.append(f"file '{out_dir / f'screen-{len(SCREENS) - 1}.png'}'")
    concat.write_text("\n".join(entries) + "\n")

    inputs = ["-f", "concat", "-safe", "0", "-i", str(concat)]
    if audio == "speech":
        speech = out_dir / "speech.aiff"
        subprocess.run(["say", "-o", str(speech), SPEECH], check=True)
        inputs += ["-i", str(speech), "-af", "apad", "-c:a", "aac"]
    elif audio == "silence":
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-c:a", "aac"]
    else:
        inputs += ["-an"]
    video = out_dir / f"reel-{audio}.mp4"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", *inputs, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", "-t", "10", str(video)],
        check=True,
    )
    return video


def _draw(text: str, path: Path) -> None:
    image = Image.new("RGB", (1080, 1920), (20, 20, 30))
    ImageDraw.Draw(image).text((80, 900), text, fill=(255, 255, 255), font=ImageFont.load_default(size=64))
    image.save(path)
