"""Ports: the small interfaces through which the pipeline core talks to the outside world."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class MessageRef:
    chat_id: int
    message_id: int


@dataclass(frozen=True)
class Message:
    update_id: int
    message_id: int
    chat_id: int
    sender_id: int
    text: str

    @property
    def ref(self) -> MessageRef:
        return MessageRef(chat_id=self.chat_id, message_id=self.message_id)


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
    categories: dict[str, str]
    """Every category an entry may be filed under, slug to description, `other` last."""


@dataclass(frozen=True)
class EntryDraft:
    summary: str
    problem: str
    """One line: the problem the reel solves."""
    approach: str
    """One line: how the reel solves it."""
    technique: str
    steps: list[str]
    prerequisites: list[str]
    when_useful: str
    caveats: list[str]
    tools: list[str]
    tags: list[str]
    category: str


class Inbox(Protocol):
    def fetch_messages(self, offset: int) -> list[Message]:
        """Messages whose update_id is at least `offset`, oldest first."""
        ...

    def react(self, ref: MessageRef, emoji: str, reason: str | None = None) -> None:
        """React to a message; `reason` is a one-line explanation shown alongside a failure."""
        ...


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
