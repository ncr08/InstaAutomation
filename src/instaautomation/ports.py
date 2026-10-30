"""Ports: the small interfaces through which the pipeline core talks to the outside world."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Message:
    message_id: int
    chat_id: int
    sender_id: int
    text: str


@dataclass(frozen=True)
class Reel:
    url: str
    shortcode: str
    creator: str
    caption: str
    video_path: Path


@dataclass(frozen=True)
class SummaryRequest:
    transcript: str
    caption: str
    on_screen_text: str
    creator: str
    index: str


@dataclass(frozen=True)
class EntryDraft:
    summary: str
    technique: str
    steps: list[str]
    prerequisites: list[str]
    when_useful: str
    caveats: list[str]
    tools: list[str]
    tags: list[str]
    topic: str


class Inbox(Protocol):
    def fetch_messages(self) -> list[Message]: ...

    def react(self, message: Message, emoji: str) -> None: ...


class ReelSource(Protocol):
    def fetch(self, url: str) -> Reel: ...


class Transcriber(Protocol):
    def transcribe(self, video_path: Path) -> str: ...


class ScreenReader(Protocol):
    def read(self, video_path: Path) -> str: ...


class Summarizer(Protocol):
    def summarize(self, request: SummaryRequest) -> EntryDraft: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True)
class Ports:
    inbox: Inbox
    reel_source: ReelSource
    transcriber: Transcriber
    screen_reader: ScreenReader
    summarizer: Summarizer
    clock: Clock
