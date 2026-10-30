"""In-memory fakes for every port, for driving run_cycle in tests."""

from datetime import datetime
from pathlib import Path

from instaautomation.ports import EntryDraft, Message, Reel, SummaryRequest


class FakeInbox:
    def __init__(self, messages: list[Message] | None = None) -> None:
        self._unread = list(messages or [])
        self.reactions: list[tuple[int, str]] = []

    def fetch_messages(self) -> list[Message]:
        fetched, self._unread = self._unread, []
        return fetched

    def react(self, message: Message, emoji: str) -> None:
        self.reactions.append((message.message_id, emoji))


class FakeReelSource:
    def __init__(self, reels: list[Reel] | None = None) -> None:
        self._reels = {reel.url: reel for reel in reels or []}

    def fetch(self, url: str) -> Reel:
        return self._reels[url]


class FakeTranscriber:
    def __init__(self, transcripts: dict[Path, str] | None = None) -> None:
        self._transcripts = dict(transcripts or {})

    def transcribe(self, video_path: Path) -> str:
        return self._transcripts[video_path]


class FakeScreenReader:
    def __init__(self, texts: dict[Path, str] | None = None) -> None:
        self._texts = dict(texts or {})

    def read(self, video_path: Path) -> str:
        return self._texts[video_path]


class FakeSummarizer:
    def __init__(self, draft: EntryDraft) -> None:
        self._draft = draft

    def summarize(self, request: SummaryRequest) -> EntryDraft:
        return self._draft


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now
