import logging
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from instaautomation.categories import CATEGORIES_FILE
from instaautomation.fakes import (
    FakeCoverMaker,
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
OTHER_SHORTCODE = "DXyz789AbC"
OTHER_VIDEO = Path(f"/videos/{OTHER_SHORTCODE}.mp4")
OTHER_LINK = f"https://www.instagram.com/reel/{OTHER_SHORTCODE}/"
THIRD_SHORTCODE = "DQrs456TuV"
THIRD_LINK = f"https://www.instagram.com/p/{THIRD_SHORTCODE}/"

SECTIONS = [
    "Summary",
    "The technique",
    "Step-by-step instructions",
    "Prerequisites",
    "When this is useful",
    "Caveats",
]


def read_markdown(path: Path) -> tuple[dict[str, object], str]:
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
    problem="Claude Code keeps asking for permission on safe commands",
    approach="Allowlist read-only commands in settings.json",
    technique="Add read-only commands to the permissions allowlist in settings.json.",
    steps=["Open ~/.claude/settings.json", "Add the commands under permissions.allow"],
    prerequisites=["Claude Code installed"],
    when_useful="When permission prompts slow you down.",
    caveats=["Never allowlist destructive commands"],
    tools=["Claude Code"],
    tags=["permissions", "productivity"],
    category="coding-agents",
)


@dataclass
class World:
    kb_dir: Path
    inbox: FakeInbox
    reel_source: FakeReelSource
    transcriber: FakeTranscriber
    screen_reader: FakeScreenReader
    summarizer: FakeSummarizer
    cover_maker: FakeCoverMaker
    next_update_id: int = 500
    now: datetime = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)

    def cycle(self) -> None:
        run_cycle(
            Ports(
                inbox=self.inbox,
                reel_source=self.reel_source,
                transcriber=self.transcriber,
                screen_reader=self.screen_reader,
                summarizer=self.summarizer,
                cover_maker=self.cover_maker,
                clock=FixedClock(self.now),
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
            # The categories file is the owner's settings, written on the first cycle, not reel content.
            if path.is_file() and path.name not in {STATE_FILE, CATEGORIES_FILE}
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
                ),
                Reel(
                    url=OTHER_LINK,
                    shortcode=OTHER_SHORTCODE,
                    creator="devflow",
                    caption="Project settings beat global ones",
                    video_path=OTHER_VIDEO,
                ),
            ]
        ),
        transcriber=FakeTranscriber(
            {VIDEO: "So here is how you stop the permission prompts.", OTHER_VIDEO: "Put it in the project."}
        ),
        screen_reader=FakeScreenReader(
            {VIDEO: '"permissions": {"allow": ["Bash(git status)"]}', OTHER_VIDEO: ".claude/settings.json"}
        ),
        summarizer=FakeSummarizer(DRAFT),
        cover_maker=FakeCoverMaker(),
    )


def test_owner_shares_a_reel_and_one_cycle_writes_an_entry_and_reacts_ok(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)
    inbox = world.inbox

    world.cycle()

    entries = list((tmp_path / "entries").glob("*.md"))
    assert len(entries) == 1
    frontmatter, body = read_markdown(entries[0])

    assert frontmatter == {
        "source_url": "https://www.instagram.com/reel/DAbc123XyZ/",
        "shortcode": "DAbc123XyZ",
        "creator": "aitipsdaily",
        "date_added": "2026-10-30",
        "category": "coding-agents",
        "problem": "Claude Code keeps asking for permission on safe commands",
        "approach": "Allowlist read-only commands in settings.json",
        "pinned": False,
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


def test_every_reel_shared_since_the_last_cycle_is_processed_not_just_the_latest(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.reel_source.add(Reel(url=THIRD_LINK, shortcode=THIRD_SHORTCODE, creator="x", caption="", video_path=OTHER_VIDEO))
    world.share(message_id=42)
    world.cycle()

    # Hours pass between scheduled cycles; several reels and some chatter pile up in the chat.
    world.share(message_id=43, text=OTHER_LINK)
    world.share(message_id=44, text="saw this one earlier")
    world.share(message_id=45, text=THIRD_LINK)
    world.cycle()

    assert sorted(path.stem for path in (tmp_path / "entries").glob("*.md")) == sorted([SHORTCODE, OTHER_SHORTCODE, THIRD_SHORTCODE])
    assert world.inbox.reactions == [(42, "✅", None), (43, "✅", None), (45, "✅", None)]


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
    assert f"entries/{SHORTCODE}.md" in world.kb_files()
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
    assert f"entries/{SHORTCODE}.md" in world.kb_files()


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

    assert sorted(path for path in world.kb_files() if path.startswith("entries/")) == [f"entries/{SHORTCODE}.jpg", f"entries/{SHORTCODE}.md"]
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
        replace(DRAFT, problem=""),
        replace(DRAFT, problem="Prompts\nkeep coming"),
        replace(DRAFT, approach="Allowlist commands\nand also edit hooks"),
        replace(DRAFT, category="no-such-category"),
        replace(DRAFT, category="../../etc/passwd"),
    ],
    ids=[
        "empty-summary",
        "blank-technique",
        "no-steps",
        "tags-not-a-list",
        "non-string-caveat",
        "empty-problem",
        "multi-line-problem",
        "multi-line-approach",
        "unknown-category",
        "path-as-category",
    ],
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


def write_categories(kb_dir: Path, text: str) -> None:
    kb_dir.mkdir(parents=True, exist_ok=True)
    (kb_dir / CATEGORIES_FILE).write_text(text)


def write_entry_file(
    kb_dir: Path, shortcode: str, *, category: str, date_added: str, pinned: bool = False
) -> None:
    path = kb_dir / "entries" / f"{shortcode}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nsource_url: https://www.instagram.com/reel/{shortcode}/\nshortcode: {shortcode}\ncreator: x\n"
        f"date_added: '{date_added}'\ncategory: {category}\nproblem: Problem of {shortcode}\n"
        f"approach: Approach of {shortcode}\npinned: {str(pinned).lower()}\ntools: []\ntags: []\n---\n\n## Summary\n\nx\n"
    )


def test_the_first_cycle_writes_the_default_categories_for_the_owner_to_edit(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)

    world.cycle()

    categories = yaml.safe_load((tmp_path / CATEGORIES_FILE).read_text())
    assert "coding-agents" in categories and "other" in categories
    assert world.summarizer.requests[-1].categories == categories


def test_the_summarizer_is_offered_the_owners_categories_plus_other(tmp_path: Path) -> None:
    write_categories(tmp_path, "# My categories\nprompting: Writing better prompts\nvideo: Making videos with AI\n")
    world = make_world(tmp_path)
    world.summarizer.draft = replace(DRAFT, category="video")
    world.share(message_id=42)

    world.cycle()

    assert world.summarizer.requests[-1].categories == {
        "prompting": "Writing better prompts",
        "video": "Making videos with AI",
        "other": "Anything that fits no other category",
    }
    frontmatter, _ = read_markdown(tmp_path / "entries" / f"{SHORTCODE}.md")
    assert frontmatter["category"] == "video"
    assert world.inbox.reactions == [(42, "✅", None)]


def test_a_category_the_owner_does_not_have_is_a_failure(tmp_path: Path) -> None:
    write_categories(tmp_path, "prompting: Writing better prompts\n")
    world = make_world(tmp_path)
    world.share(message_id=42)

    world.cycle()

    assert world.kb_files() == {}
    [item] = load_state(tmp_path).pending
    assert item.attempts == 1
    assert "coding-agents" in (item.last_error or "")


def test_a_reel_that_fits_no_category_is_filed_under_other(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.summarizer.draft = replace(DRAFT, category="other")
    world.share(message_id=42)

    world.cycle()

    assert world.inbox.reactions == [(42, "✅", None)]
    assert "## Other" in (tmp_path / "index.md").read_text()


def test_the_index_lists_every_entry_under_its_category_in_the_owners_order(tmp_path: Path) -> None:
    write_categories(tmp_path, "video: Making videos\nprompting: Writing better prompts\n")
    write_entry_file(tmp_path, "DOldPrompt1", category="prompting", date_added="2026-10-01")
    write_entry_file(tmp_path, "DNewPrompt1", category="prompting", date_added="2026-10-20")
    write_entry_file(tmp_path, "DVideo00001", category="video", date_added="2026-09-01")
    write_entry_file(tmp_path, "DStale00001", category="removed-category", date_added="2026-09-01")
    world = make_world(tmp_path)

    world.cycle()

    index = (tmp_path / "index.md").read_text()
    assert re.findall(r"^## (.+)$", index, re.MULTILINE) == ["Video", "Prompting", "Other"]
    lines = re.findall(r"^- .*$", index, re.MULTILINE)
    assert lines == [
        "- Problem of DVideo00001 → Approach of DVideo00001 ([DVideo00001](entries/DVideo00001.md), 2026-09-01)",
        "- Problem of DNewPrompt1 → Approach of DNewPrompt1 ([DNewPrompt1](entries/DNewPrompt1.md), 2026-10-20)",
        "- Problem of DOldPrompt1 → Approach of DOldPrompt1 ([DOldPrompt1](entries/DOldPrompt1.md), 2026-10-01)",
        "- Problem of DStale00001 → Approach of DStale00001 ([DStale00001](entries/DStale00001.md), 2026-09-01)",
    ]
    assert "Writing better prompts" in index


def test_a_new_entry_appears_in_the_index_and_the_claude_block(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)

    world.cycle()

    line = (
        "- Claude Code keeps asking for permission on safe commands → "
        "Allowlist read-only commands in settings.json"
    )
    assert f"{line} ([{SHORTCODE}](entries/{SHORTCODE}.md), 2026-10-30)" in (tmp_path / "index.md").read_text()
    assert f"{line} (see entries/{SHORTCODE}.md)" in (tmp_path / "claude-block.md").read_text()


def test_the_claude_block_lists_pinned_entries_then_the_newest_of_each_category_in_turn_and_is_capped(
    tmp_path: Path,
) -> None:
    write_categories(tmp_path, "aa: First\nbb: Second\n")
    write_entry_file(tmp_path, "DPinnedOld1", category="bb", date_added="2026-01-01", pinned=True)
    for day in range(1, 11):
        write_entry_file(tmp_path, f"DAa{day:08d}", category="aa", date_added=f"2026-10-{day:02d}")
        write_entry_file(tmp_path, f"DBb{day:08d}", category="bb", date_added=f"2026-09-{day:02d}")
    # Same day as the newest aa entry: ties go by shortcode, so the order never depends on the file system.
    write_entry_file(tmp_path, "DAa00000010x", category="aa", date_added="2026-10-10")
    world = make_world(tmp_path)

    world.cycle()

    block = (tmp_path / "claude-block.md").read_text()
    ranked = re.findall(r"^- Problem of (\S+) → Approach of \1 \(see entries/\1\.md\)", block, re.MULTILINE)
    assert ranked == [
        "DPinnedOld1",
        "DAa00000010x",
        "DBb00000010",
        "DAa00000010",
        "DBb00000009",
        "DAa00000009",
        "DBb00000008",
        "DAa00000008",
        "DBb00000007",
        "DAa00000007",
        "DBb00000006",
        "DAa00000006",
        "DBb00000005",
        "DAa00000005",
        "DBb00000004",
    ]
    last_line = block.strip().splitlines()[-1]
    assert "index.md" in last_line and "/ai-kb" in last_line


def test_hand_edited_entry_files_are_read_leniently(tmp_path: Path) -> None:
    path = tmp_path / "entries" / "DHandEdit01.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(
        b"---\r\nshortcode: DHandEdit01\r\ndate_added: 2026-10-01\r\ncategory: coding-agents\r\n"
        b'problem: Odd YAML\r\napproach: Tolerate it\r\npinned: "false"\r\n---\r\n\r\nBody.\r\n'
    )
    write_entry_file(tmp_path, "DPinned0001", category="coding-agents", date_added="2026-01-01", pinned=True)
    (tmp_path / "entries" / "notes.txt").write_text("not an entry")
    world = make_world(tmp_path)

    world.cycle()

    block = (tmp_path / "claude-block.md").read_text()
    assert block.index("Problem of DPinned0001") < block.index("Odd YAML")
    assert "Odd YAML → Tolerate it ([DHandEdit01](entries/DHandEdit01.md), 2026-10-01)" in (tmp_path / "index.md").read_text()


def test_a_reel_whose_entry_was_written_just_before_a_crash_is_still_added_on_retry(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)
    break_port(world, "transcriber", RuntimeError("Groq timeout"))
    world.cycle()
    state_before_success = (tmp_path / STATE_FILE).read_text()
    world.cycle()

    # The runner died after the KB writes but before the state was saved.
    (tmp_path / STATE_FILE).write_text(state_before_success)
    world.cycle()

    assert load_state(tmp_path).pending == []
    assert world.inbox.reactions[-1] == (42, "✅", None)
    assert sorted(path for path in world.kb_files() if path.startswith("entries/")) == [f"entries/{SHORTCODE}.jpg", f"entries/{SHORTCODE}.md"]


def test_a_broken_categories_file_fails_the_cycle_without_using_up_the_reels_attempts(tmp_path: Path) -> None:
    write_categories(tmp_path, "- prompting\n- video\n")
    world = make_world(tmp_path)
    world.share(message_id=42)

    with pytest.raises(ValueError, match="categories"):
        world.cycle()

    [item] = load_state(tmp_path).pending
    assert item.attempts == 0
    assert world.summarizer.requests == []


def reel_log(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The per-reel lines a run prints, the outcome word first, for reading in the Actions log."""
    return [record.getMessage() for record in caplog.records if record.name == "instaautomation.pipeline" and record.levelno == logging.INFO]


def test_the_log_lists_a_new_reel_as_queued_then_processed(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    world = make_world(tmp_path)
    world.share(message_id=42)

    world.cycle()

    assert reel_log(caplog) == [
        f"queued {SHORTCODE}",
        f"processed {SHORTCODE} into coding-agents",
    ]


def test_the_log_lists_each_failed_attempt_and_the_reel_given_up_on(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    world = make_world(tmp_path)
    world.share(message_id=42)
    world.transcriber.fail_next(TimeoutError("Groq timed out"), times=3)

    for _ in range(3):
        world.cycle()

    assert reel_log(caplog) == [
        f"queued {SHORTCODE}",
        f"failed {SHORTCODE}, attempt 1/3, will retry: TimeoutError: Groq timed out",
        f"failed {SHORTCODE}, attempt 2/3, will retry: TimeoutError: Groq timed out",
        f"failed {SHORTCODE}, gave up after 3 attempts: TimeoutError: Groq timed out",
    ]


def test_the_log_lists_a_repeat_share_as_skipped(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)
    world.cycle()
    world.transcriber.fail_next(TimeoutError("Groq timed out"))
    world.share(message_id=43, text=OTHER_LINK)
    world.cycle()
    # Only now: the cycles above just set the scene.
    caplog.set_level(logging.INFO)

    world.share(message_id=44)
    world.share(message_id=45, text=OTHER_LINK)
    world.transcriber.fail_next(TimeoutError("Groq timed out"))
    world.cycle()

    assert reel_log(caplog) == [
        f"skipped {SHORTCODE}: already added",
        f"skipped {OTHER_SHORTCODE}: already queued",
        f"failed {OTHER_SHORTCODE}, attempt 2/3, will retry: TimeoutError: Groq timed out",
    ]


def test_the_reels_cover_is_saved_next_to_its_entry(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)

    world.cycle()

    assert (tmp_path / "entries" / f"{SHORTCODE}.jpg").read_bytes() == FakeCoverMaker.cover_for(SHORTCODE)


def test_a_cover_failure_still_adds_the_reel_and_only_logs_a_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    world = make_world(tmp_path)
    world.share(message_id=42)
    world.cover_maker.fail_next(RuntimeError("cover URL expired"))

    world.cycle()

    assert (tmp_path / "entries" / f"{SHORTCODE}.md").exists()
    assert not (tmp_path / "entries" / f"{SHORTCODE}.jpg").exists()
    state = load_state(tmp_path)
    assert state.processed == {SHORTCODE}
    assert state.pending == [] and state.failed == []
    assert world.inbox.reactions == [(42, "✅", None)]
    assert reel_log(caplog) == [f"queued {SHORTCODE}", f"processed {SHORTCODE} into coding-agents"]
    [warning] = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert SHORTCODE in warning.getMessage()
