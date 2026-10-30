"""Manual smoke tests for the media adapters on generated sample reels. Need ffmpeg, tesseract, macOS `say`
and a Groq key; CI never runs them.

    set -a; source .env; set +a
    RUN_SMOKE=1 uv run pytest tests/smoke/test_live_media.py -s
"""

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from instaautomation.groq import GroqTranscriber
from instaautomation.ocr import OcrScreenReader

pytestmark = pytest.mark.skipif(os.environ.get("RUN_SMOKE") != "1", reason="live smoke test; set RUN_SMOKE=1")


def test_groq_transcribes_speech(sample_reel: Callable[..., Path]) -> None:
    transcript = GroqTranscriber.from_env().transcribe(sample_reel("speech"))

    print(repr(transcript))
    assert "settings file" in transcript.lower()


def test_a_silent_track_transcribes_to_nothing(sample_reel: Callable[..., Path]) -> None:
    transcript = GroqTranscriber.from_env().transcribe(sample_reel("silence"))

    print(repr(transcript))
    assert transcript == ""


def test_a_video_without_audio_transcribes_to_nothing_without_calling_groq(sample_reel: Callable[..., Path]) -> None:
    transcript = GroqTranscriber("not-a-real-key").transcribe(sample_reel("none"))

    assert transcript == ""


def test_on_screen_text_is_read_once_with_typed_text_complete(sample_reel: Callable[..., Path]) -> None:
    text = OcrScreenReader().read(sample_reel("none"))

    print(text)
    assert text.splitlines() == ["Stop clicking approve", "claude --permission-mode plan"]
