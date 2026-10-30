"""Thin wrappers over the ffmpeg and tesseract command-line tools."""

import re
import subprocess
from pathlib import Path

# Peaks quieter than this are a silent track: Whisper would only invent words for it.
SILENT_BELOW_DB = -50.0
# Words tesseract is less sure of than this are mostly misreads of backgrounds and faces.
MIN_WORD_CONFIDENCE = 60


class ToolError(RuntimeError):
    """A media tool is missing, failed, or took too long."""


def run_tool(args: list[str], timeout: float = 300, *, stderr: bool = False) -> str:
    """The tool's stdout, or its stderr for tools such as ffmpeg's filters that report there."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise ToolError(f"{args[0]} is not installed") from None
    except subprocess.TimeoutExpired:
        raise ToolError(f"{args[0]} timed out after {timeout:.0f}s") from None
    if result.returncode != 0:
        last_line = (result.stderr.strip().splitlines() or ["no output"])[-1]
        raise ToolError(f"{args[0]} failed: {last_line[:120]}")
    return result.stderr if stderr else result.stdout


def extract_audio(video_path: Path, out_dir: Path) -> Path | None:
    """The first audio track as 16 kHz mono FLAC (small, and what Whisper resamples to anyway),
    or None if there is no track or it is silent."""
    streams = run_tool(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(video_path)])
    if not streams.strip():
        return None
    audio = out_dir / "audio.flac"
    run_tool(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(video_path), "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-c:a", "flac", str(audio)])
    return None if _peak_db(audio) < SILENT_BELOW_DB else audio


def _peak_db(audio: Path) -> float:
    report = run_tool(["ffmpeg", "-nostdin", "-v", "info", "-i", str(audio), "-af", "volumedetect", "-f", "null", "-"], stderr=True)
    match = re.search(r"max_volume: (-?[\d.]+|-inf) dB", report)
    if not match:
        raise ToolError("ffmpeg volumedetect gave no max_volume")
    return float(match.group(1))


def sample_frames(video_path: Path, out_dir: Path, every_seconds: float) -> list[Path]:
    """One greyscale frame every `every_seconds`, in playback order."""
    pattern = out_dir / "frame-%05d.png"
    run_tool(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(video_path), "-vf", f"fps=1/{every_seconds},format=gray", str(pattern)])
    return sorted(out_dir.glob("frame-*.png"))


def ocr(image: Path) -> str:
    """The text in an image, one line per line on screen, without words tesseract is unsure of."""
    tsv = run_tool(["tesseract", str(image), "stdout", "-l", "eng", "--psm", "3", "tsv"], timeout=60)
    lines: dict[tuple[str, str, str], list[str]] = {}
    for row in tsv.splitlines()[1:]:
        columns = row.split("\t")
        # Level 5 rows are words: level, page, block, paragraph, line, word, 4 box columns, confidence, text.
        if len(columns) < 12 or columns[0] != "5" or not columns[11].strip():
            continue
        if float(columns[10]) >= MIN_WORD_CONFIDENCE:
            lines.setdefault((columns[2], columns[3], columns[4]), []).append(columns[11])
    return "\n".join(" ".join(words) for words in lines.values())


def extract_frame(video_path: Path, out: Path, at_seconds: float) -> None:
    """One full-colour frame at `at_seconds`, or the first frame of a video shorter than that."""
    for seek in (["-ss", str(at_seconds)], []):
        # Seeking past the end exits cleanly with no frame written, hence the retry from the start.
        run_tool(["ffmpeg", "-nostdin", "-v", "error", "-y", *seek, "-i", str(video_path), "-frames:v", "1", "-update", "1", str(out)])
        if out.exists() and out.stat().st_size:
            return
    raise ToolError(f"ffmpeg found no frame in {video_path.name}")


def to_jpeg(image: Path, out: Path, width: int) -> None:
    """The image as a JPEG at most `width` pixels wide, keeping its aspect ratio."""
    scale = f"scale='min({width},iw)':-2"
    run_tool(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(image), "-vf", scale, "-q:v", "4", "-frames:v", "1", "-update", "1", str(out)])
