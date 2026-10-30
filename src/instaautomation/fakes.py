"""In-memory fakes for every port, for driving run_cycle and the frontend in tests."""

from datetime import datetime
from pathlib import Path

from instaautomation.ports import CycleRun, EntryDraft, Message, MessageRef, Reel, SummaryRequest


class _Failable:
    """Lets a test make the next calls to a fake raise."""

    def __init__(self) -> None:
        self._failures: list[BaseException] = []

    def fail_next(self, error: BaseException, times: int = 1) -> None:
        self._failures.extend([error] * times)

    def _maybe_fail(self) -> None:
        if self._failures:
            raise self._failures.pop(0)


class FakeInbox(_Failable):
    """Keeps every message, like Telegram does until an offset past it is requested."""

    def __init__(self, messages: list[Message] | None = None) -> None:
        super().__init__()
        self._messages = list(messages or [])
        self.reactions: list[tuple[int, str, str | None]] = []

    def send(self, message: Message) -> None:
        self._messages.append(message)

    def expire_all(self) -> None:
        """Telegram's 24-hour retention: unfetched messages are gone for good."""
        self._messages = []

    def fetch_messages(self, offset: int) -> list[Message]:
        return [message for message in self._messages if message.update_id >= offset]

    def react(self, ref: MessageRef, emoji: str, reason: str | None = None) -> None:
        self._maybe_fail()
        self.reactions.append((ref.message_id, emoji, reason))


class FakeReelSource(_Failable):
    def __init__(self, reels: list[Reel] | None = None) -> None:
        super().__init__()
        self._reels = {reel.url: reel for reel in reels or []}

    def add(self, reel: Reel) -> None:
        self._reels[reel.url] = reel

    def fetch(self, url: str) -> Reel:
        self._maybe_fail()
        return self._reels[url]


class FakeTranscriber(_Failable):
    def __init__(self, transcripts: dict[Path, str] | None = None) -> None:
        super().__init__()
        self._transcripts = dict(transcripts or {})

    def transcribe(self, video_path: Path) -> str:
        self._maybe_fail()
        return self._transcripts[video_path]


class FakeScreenReader(_Failable):
    def __init__(self, texts: dict[Path, str] | None = None) -> None:
        super().__init__()
        self._texts = dict(texts or {})

    def read(self, video_path: Path) -> str:
        self._maybe_fail()
        return self._texts[video_path]


class FakeSummarizer(_Failable):
    def __init__(self, draft: EntryDraft) -> None:
        super().__init__()
        self.draft = draft
        self.requests: list[SummaryRequest] = []

    def summarize(self, request: SummaryRequest) -> EntryDraft:
        self.requests.append(request)
        self._maybe_fail()
        return self.draft


class FakeCoverMaker(_Failable):
    def __init__(self) -> None:
        super().__init__()
        self.made: list[str] = []

    @staticmethod
    def cover_for(shortcode: str) -> bytes:
        return f"cover of {shortcode}".encode()

    def make(self, reel: Reel) -> bytes:
        self._maybe_fail()
        self.made.append(reel.shortcode)
        return self.cover_for(reel.shortcode)


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class FakeUpdater:
    def __init__(self, failure: str | None = None) -> None:
        self._failure = failure
        self.calls = 0

    def update(self) -> str | None:
        self.calls += 1
        return self._failure


class FakeCycleRuns:
    def __init__(self, runs: list[CycleRun] | None) -> None:
        """None stands for gh being missing or logged out."""
        self._runs = runs

    def latest(self) -> list[CycleRun] | None:
        return self._runs
