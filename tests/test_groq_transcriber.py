import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from instaautomation.groq import GroqTranscriber, TranscriptionError

VIDEO = Path("/videos/DAbc123XyZ.mp4")


def segment(text: str) -> dict[str, Any]:
    return {"text": text, "no_speech_prob": 0, "avg_logprob": -0.3}


class FakeGroq:
    def __init__(self, segments: list[dict[str, Any]] | None = None, status: int = 200) -> None:
        self.segments = segments or []
        self.status = status
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "Rate limit reached", "type": "tokens"}})
        text = "".join(s["text"] for s in self.segments)
        return httpx.Response(200, json={"text": text, "segments": self.segments})


class FakeAudio:
    """Stands in for ffmpeg: a video either has audible audio, extracted to a file, or none."""

    def __init__(self, has_audio: bool = True) -> None:
        self.has_audio = has_audio

    def __call__(self, video_path: Path, out_dir: Path) -> Path | None:
        if not self.has_audio:
            return None
        audio = out_dir / "audio.flac"
        audio.write_bytes(b"fLaC fake audio")
        return audio


def transcriber_for(groq: FakeGroq, audio: FakeAudio | None = None) -> GroqTranscriber:
    return GroqTranscriber(
        api_key="gsk-secret",
        client=httpx.Client(transport=httpx.MockTransport(groq.handle)),
        extract_audio=audio or FakeAudio(),
    )


def test_speech_becomes_the_transcript() -> None:
    groq = FakeGroq([segment(" Open your settings file."), segment(" Add the allowlist.")])

    transcript = transcriber_for(groq).transcribe(VIDEO)

    assert transcript == "Open your settings file. Add the allowlist."


def test_a_video_without_audible_audio_is_an_empty_transcript_without_a_paid_call() -> None:
    groq = FakeGroq()

    transcript = transcriber_for(groq, FakeAudio(has_audio=False)).transcribe(VIDEO)

    assert transcript == ""
    assert groq.requests == []


def test_whispers_stock_phrase_for_music_or_silence_is_not_a_transcript() -> None:
    groq = FakeGroq([segment(" Thank you.")])

    assert transcriber_for(groq).transcribe(VIDEO) == ""


def test_the_stock_phrase_inside_real_speech_is_kept() -> None:
    groq = FakeGroq([segment(" Add the allowlist."), segment(" Thank you.")])

    assert transcriber_for(groq).transcribe(VIDEO) == "Add the allowlist. Thank you."


def test_sends_the_extracted_audio_to_whisper_large_v3_turbo() -> None:
    groq = FakeGroq([segment(" hi")])

    transcriber_for(groq).transcribe(VIDEO)

    request = groq.requests[0]
    assert str(request.url) == "https://api.groq.com/openai/v1/audio/transcriptions"
    assert request.headers["authorization"] == "Bearer gsk-secret"
    assert b'name="model"\r\n\r\nwhisper-large-v3-turbo' in request.content
    assert b"fLaC fake audio" in request.content


def test_a_groq_error_is_a_short_failure_without_the_key() -> None:
    with pytest.raises(TranscriptionError, match="429.*Rate limit reached") as raised:
        transcriber_for(FakeGroq(status=429)).transcribe(VIDEO)

    assert "gsk-secret" not in str(raised.value)
