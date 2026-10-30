"""Transcriber adapter over Groq's hosted Whisper."""

import logging
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from instaautomation import media

TRANSCRIPTIONS = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = "whisper-large-v3-turbo"
# What Whisper says when given music or silence. Groq reports no_speech_prob 0 for these,
# so they are recognised by text: a transcript that is nothing but one of them is no transcript.
STOCK_PHRASES = {"thank you", "thanks for watching", "thank you for watching", "you", "bye"}

log = logging.getLogger(__name__)

AudioExtractor = Callable[[Path, Path], Path | None]
"""Writes a video's audio into a directory and returns the file, or None when there is nothing audible."""


class TranscriptionError(RuntimeError):
    """The audio couldn't be transcribed."""


class GroqTranscriber:
    def __init__(self, api_key: str, client: httpx.Client | None = None, extract_audio: AudioExtractor | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=120)
        self._extract_audio = extract_audio or media.extract_audio

    def transcribe(self, video_path: Path) -> str:
        with tempfile.TemporaryDirectory(prefix="audio-") as work_dir:
            audio = self._extract_audio(video_path, Path(work_dir))
            if audio is None:
                # A silent reel: caption and on-screen text carry it. Logged in case a source starts
                # handing over video-only files, which would otherwise look like silent reels forever.
                log.warning("no audible audio in %s; transcript left empty", video_path.name)
                return ""
            response = self._client.post(
                TRANSCRIPTIONS,
                headers={"Authorization": f"Bearer {self._api_key}"},
                data={"model": MODEL, "response_format": "verbose_json", "temperature": "0"},
                files={"file": (audio.name, audio.read_bytes())},
            )
        if response.status_code != 200:
            raise TranscriptionError(f"Groq {response.status_code}: {_error_message(response)}")
        body: dict[str, Any] = response.json()
        transcript = " ".join(segment["text"].strip() for segment in body["segments"]).strip()
        return "" if _normalised(transcript) in STOCK_PHRASES else transcript


def _error_message(response: httpx.Response) -> str:
    try:
        body: Any = response.json()
        message = body["error"]["message"]
    except (ValueError, KeyError, TypeError):
        message = response.text
    return str(message)[:120]


def _normalised(text: str) -> str:
    return re.sub(r"[^a-z ]+", "", text.lower()).strip()
