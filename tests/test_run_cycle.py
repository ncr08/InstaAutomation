import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from instaautomation.fakes import (
    FakeInbox,
    FakeReelSource,
    FakeScreenReader,
    FakeSummarizer,
    FakeTranscriber,
    FixedClock,
)
from instaautomation.pipeline import run_cycle
from instaautomation.ports import EntryDraft, Message, Ports, Reel
from instaautomation.state import STATE_FILE, load_state

OWNER_ID = 1001
VIDEO = Path("/videos/DAbc123XyZ.mp4")

SECTIONS = [
    "Summary",
    "The technique",
    "Step-by-step instructions",
    "Prerequisites",
    "When this is useful",
    "Caveats",
]


def read_entry(path: Path) -> tuple[dict[str, object], str]:
    match = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", path.read_text(), re.DOTALL)
    assert match, "entry must start with a YAML frontmatter block"
    frontmatter = yaml.safe_load(match.group(1))
    assert isinstance(frontmatter, dict)
    return frontmatter, match.group(2)


def section(body: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |^<details>|\Z)", body, re.DOTALL | re.MULTILINE)
    assert match, f"missing section: {heading}"
    return match.group(1)


SHORTCODE = "DAbc123XyZ"
REEL_URL = f"https://www.instagram.com/reel/{SHORTCODE}/"
SHARED_LINK = f"{REEL_URL}?igsh=MWQ1ZGUxMzBkMA=="
DRAFT = EntryDraft(
    summary="Allowlist safe commands so Claude Code stops asking.",
    technique="Add read-only commands to the permissions allowlist in settings.json.",
    steps=["Open ~/.claude/settings.json", "Add the commands under permissions.allow"],
    prerequisites=["Claude Code installed"],
    when_useful="When permission prompts slow you down.",
    caveats=["Never allowlist destructive commands"],
    tools=["Claude Code"],
    tags=["permissions", "productivity"],
    topic="slow-permission-prompts",
)


@dataclass
class World:
    kb_dir: Path
    inbox: FakeInbox
    reel_source: FakeReelSource
    transcriber: FakeTranscriber
    screen_reader: FakeScreenReader
    summarizer: FakeSummarizer
    next_update_id: int = 500

    def cycle(self) -> None:
        run_cycle(
            Ports(
                inbox=self.inbox,
                reel_source=self.reel_source,
                transcriber=self.transcriber,
                screen_reader=self.screen_reader,
                summarizer=self.summarizer,
                clock=FixedClock(datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)),
            ),
            self.kb_dir,
            owner_id=OWNER_ID,
        )

    def share(self, message_id: int, text: str = SHARED_LINK, sender_id: int = OWNER_ID) -> None:
        self.inbox.send(
            Message(
                update_id=self.next_update_id,
                message_id=message_id,
                chat_id=sender_id,
                sender_id=sender_id,
                text=text,
            )
        )
        self.next_update_id += 1

    def kb_files(self) -> dict[str, bytes]:
        """Every knowledge-base file and its contents, excluding pipeline state."""
        return {
            str(path.relative_to(self.kb_dir)): path.read_bytes()
            for path in self.kb_dir.rglob("*")
            if path.is_file() and path.name != STATE_FILE
        }


def make_world(kb_dir: Path) -> World:
    return World(
        kb_dir=kb_dir,
        inbox=FakeInbox(),
        reel_source=FakeReelSource(
            [
                Reel(
                    url=REEL_URL,
                    shortcode=SHORTCODE,
                    creator="aitipsdaily",
                    caption="Stop clicking allow on every prompt",
                    video_path=VIDEO,
                )
            ]
        ),
        transcriber=FakeTranscriber({VIDEO: "So here is how you stop the permission prompts."}),
        screen_reader=FakeScreenReader({VIDEO: '"permissions": {"allow": ["Bash(git status)"]}'}),
        summarizer=FakeSummarizer(DRAFT),
    )


def test_owner_shares_a_reel_and_one_cycle_writes_an_entry_and_reacts_ok(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)
    inbox = world.inbox

    world.cycle()

    entries = list(tmp_path.rglob("*.md"))
    assert len(entries) == 1
    frontmatter, body = read_entry(entries[0])

    assert frontmatter == {
        "source_url": "https://www.instagram.com/reel/DAbc123XyZ/",
        "shortcode": "DAbc123XyZ",
        "creator": "aitipsdaily",
        "date_added": "2026-10-30",
        "topic": "slow-permission-prompts",
        "tools": ["Claude Code"],
        "tags": ["permissions", "productivity"],
    }

    headings = re.findall(r"^## (.+)$", body, re.MULTILINE)
    assert headings == SECTIONS
    assert "Allowlist safe commands so Claude Code stops asking." in section(body, "Summary")
    assert "permissions allowlist in settings.json" in section(body, "The technique")
    steps = section(body, "Step-by-step instructions")
    assert "1. Open ~/.claude/settings.json" in steps
    assert "2. Add the commands under permissions.allow" in steps
    assert "Claude Code installed" in section(body, "Prerequisites")
    assert "When permission prompts slow you down." in section(body, "When this is useful")
    assert "Never allowlist destructive commands" in section(body, "Caveats")

    raw = re.search(r"<details>(.*?)</details>\s*\Z", body, re.DOTALL)
    assert raw, "raw transcript and on-screen text must be in a collapsed block at the bottom"
    assert "So here is how you stop the permission prompts." in raw.group(1)
    assert '"permissions": {"allow": ["Bash(git status)"]}' in raw.group(1)

    assert inbox.reactions == [(42, "✅", None)]


def test_update_offset_persists_so_a_later_cycle_does_not_refetch_the_same_message(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)

    world.cycle()
    world.cycle()

    assert world.inbox.reactions == [(42, "✅", None)]
    assert load_state(tmp_path).offset == 501


def test_messages_from_anyone_but_the_owner_are_ignored(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42, sender_id=666)

    world.cycle()

    assert world.inbox.reactions == []
    assert world.kb_files() == {}


def test_messages_without_an_instagram_reel_or_post_link_are_ignored(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42, text="hey, check this out later")
    world.share(message_id=43, text="https://www.youtube.com/shorts/abc123")

    world.cycle()

    assert world.inbox.reactions == []
    assert world.kb_files() == {}
    assert load_state(tmp_path).offset == 502


FAILING_PORTS = ["reel_source", "transcriber", "screen_reader", "summarizer"]


def break_port(world: World, port: str, error: BaseException, times: int = 1) -> None:
    fake: FakeReelSource | FakeTranscriber | FakeScreenReader | FakeSummarizer = getattr(world, port)
    fake.fail_next(error, times)


@pytest.mark.parametrize("port", FAILING_PORTS)
def test_a_failure_in_any_port_leaves_the_reel_pending_and_a_later_cycle_processes_it(
    tmp_path: Path, port: str
) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)
    break_port(world, port, RuntimeError("service unavailable"))

    world.cycle()

    assert world.inbox.reactions == []
    assert world.kb_files() == {}
    [item] = load_state(tmp_path).pending
    assert (item.shortcode, item.url, item.ref.message_id, item.attempts) == (SHORTCODE, REEL_URL, 42, 1)
    assert "service unavailable" in (item.last_error or "")

    world.cycle()

    assert world.inbox.reactions == [(42, "✅", None)]
    assert list(world.kb_files()) == [f"entries/{SHORTCODE}.md"]
    assert load_state(tmp_path).pending == []


def test_third_failure_moves_the_reel_to_the_failed_list_and_reacts_with_a_one_line_reason(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)
    break_port(world, "reel_source", RuntimeError("HikerAPI returned 404:\nmedia not found"), times=3)

    world.cycle()
    world.cycle()
    assert load_state(tmp_path).pending[0].attempts == 2
    assert world.inbox.reactions == []

    world.cycle()

    state = load_state(tmp_path)
    assert state.pending == []
    [item] = state.failed
    assert (item.shortcode, item.attempts) == (SHORTCODE, 3)
    [(message_id, emoji, reason)] = world.inbox.reactions
    assert (message_id, emoji) == (42, "❌")
    assert reason is not None and "\n" not in reason
    assert "HikerAPI returned 404: media not found" in reason
    assert world.kb_files() == {}

    world.cycle()

    assert len(world.inbox.reactions) == 1


class Crash(BaseException):
    """Simulates the runner dying mid-cycle (killed job, OOM), which no except clause should swallow."""


def test_a_crash_after_enqueue_does_not_lose_the_reel(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)
    break_port(world, "reel_source", Crash())

    with pytest.raises(Crash):
        world.cycle()
    world.inbox.expire_all()

    world.cycle()

    assert world.inbox.reactions == [(42, "✅", None)]
    assert list(world.kb_files()) == [f"entries/{SHORTCODE}.md"]


def test_sharing_an_already_added_reel_again_reacts_ok_and_changes_nothing(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)
    world.cycle()
    kb_before = world.kb_files()
    world.summarizer.draft = replace(DRAFT, summary="A different summary that must never be written.")

    world.share(message_id=43, text=f"https://instagram.com/reel/{SHORTCODE}")
    world.cycle()

    assert world.inbox.reactions == [(42, "✅", None), (43, "✅", None)]
    assert world.kb_files() == kb_before
    assert load_state(tmp_path).pending == []


def test_sharing_a_reel_that_is_still_pending_does_not_queue_it_twice(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)
    break_port(world, "transcriber", RuntimeError("Groq timeout"))
    world.cycle()

    world.share(message_id=43)
    world.cycle()

    [entry] = world.kb_files()
    assert entry == f"entries/{SHORTCODE}.md"
    assert world.inbox.reactions == [(42, "✅", None)]
    assert load_state(tmp_path).pending == []


@pytest.mark.parametrize(
    "malformed",
    [
        replace(DRAFT, summary=""),
        replace(DRAFT, technique="   "),
        replace(DRAFT, steps=[]),
        replace(DRAFT, tags="permissions"),  # type: ignore[arg-type]
        replace(DRAFT, caveats=[None]),  # type: ignore[list-item]
        replace(DRAFT, topic="../../etc/passwd"),
        replace(DRAFT, topic="Slow Permission Prompts"),
    ],
    ids=["empty-summary", "blank-technique", "no-steps", "tags-not-a-list", "non-string-caveat", "path-in-topic", "topic-not-a-slug"],
)
def test_malformed_summarizer_output_is_a_failure_and_leaves_the_kb_untouched(
    tmp_path: Path, malformed: EntryDraft
) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)
    world.summarizer.draft = malformed

    world.cycle()

    assert world.kb_files() == {}
    assert world.inbox.reactions == []
    [item] = load_state(tmp_path).pending
    assert item.attempts == 1


def test_a_rejected_reaction_does_not_block_the_queue(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)
    world.cycle()
    world.inbox.fail_next(RuntimeError("Bad Request: message to react not found"))

    world.share(message_id=43)
    world.share(message_id=44, text="https://www.instagram.com/p/OtherPost1/")
    world.cycle()

    state = load_state(tmp_path)
    assert state.offset == 503
    [item] = state.pending
    assert (item.shortcode, item.attempts) == ("OtherPost1", 1)


def test_resending_a_failed_reel_takes_it_off_the_failed_list_once_it_succeeds(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)
    break_port(world, "reel_source", RuntimeError("HikerAPI down"), times=3)
    for _ in range(3):
        world.cycle()

    world.share(message_id=43)
    world.cycle()

    state = load_state(tmp_path)
    assert state.failed == []
    assert state.pending == []
    assert world.inbox.reactions[-1] == (43, "✅", None)
