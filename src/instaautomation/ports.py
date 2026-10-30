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


MAX_TOPICS = 10
"""The knowledge base never grows past this many topics, the unsorted one included."""
UNSORTED_TOPIC = "unsorted"
"""The catch-all topic for reels that fit no other; created by the core the first time a reel is filed there."""


@dataclass(frozen=True)
class SummaryRequest:
    transcript: str
    caption: str
    on_screen_text: str
    creator: str
    index: str
    topics: dict[str, str]
    """Current guidance body of every topic, by slug, so an existing topic can be merged into."""
    can_create_topic: bool
    """False once the knowledge base is full: the reel must go under an existing topic or the unsorted one."""


@dataclass(frozen=True)
class ExistingTopic:
    slug: str


@dataclass(frozen=True)
class NewTopic:
    slug: str
    title: str
    problem: str


@dataclass(frozen=True)
class TopicDecision:
    """Where a reel belongs, plus the topic's guidance rewritten to include it."""

    target: ExistingTopic | NewTopic
    approach: str
    body: str


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
    topic: TopicDecision


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
