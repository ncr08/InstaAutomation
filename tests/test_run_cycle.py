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
from instaautomation.ports import EntryDraft, ExistingTopic, Message, NewTopic, Ports, Reel, TopicDecision
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
    technique="Add read-only commands to the permissions allowlist in settings.json.",
    steps=["Open ~/.claude/settings.json", "Add the commands under permissions.allow"],
    prerequisites=["Claude Code installed"],
    when_useful="When permission prompts slow you down.",
    caveats=["Never allowlist destructive commands"],
    tools=["Claude Code"],
    tags=["permissions", "productivity"],
    topic=TopicDecision(
        target=NewTopic(
            slug="slow-permission-prompts",
            title="Slow permission prompts",
            problem="Claude Code keeps asking for permission on safe commands",
        ),
        approach="Allowlist read-only commands in settings.json",
        body="Add safe, read-only commands to `permissions.allow` so they run without a prompt.",
    ),
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
    now: datetime = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)

    def cycle(self) -> None:
        run_cycle(
            Ports(
                inbox=self.inbox,
                reel_source=self.reel_source,
                transcriber=self.transcriber,
                screen_reader=self.screen_reader,
                summarizer=self.summarizer,
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


def test_every_reel_shared_since_the_last_cycle_is_processed_not_just_the_latest(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.reel_source.add(Reel(url=THIRD_LINK, shortcode=THIRD_SHORTCODE, creator="x", caption="", video_path=OTHER_VIDEO))
    world.share(message_id=42)
    world.cycle()

    # Hours pass between scheduled cycles; several reels and some chatter pile up in the chat.
    world.summarizer.draft = replace(
        DRAFT,
        topic=TopicDecision(
            target=ExistingTopic(slug="slow-permission-prompts"), approach="Allowlist", body=f"{DRAFT.topic.body}\n\nMerged."
        ),
    )
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

    assert [path for path in world.kb_files() if path.startswith("entries/")] == [f"entries/{SHORTCODE}.md"]
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
        replace(DRAFT, topic=replace(DRAFT.topic, target=replace(DRAFT.topic.target, slug="../../etc/passwd"))),
        replace(DRAFT, topic=replace(DRAFT.topic, target=replace(DRAFT.topic.target, slug="Slow Permission Prompts"))),
        replace(DRAFT, topic=replace(DRAFT.topic, approach="Allowlist commands\nand also edit hooks")),
        replace(DRAFT, topic=replace(DRAFT.topic, body="  ")),
    ],
    ids=[
        "empty-summary",
        "blank-technique",
        "no-steps",
        "tags-not-a-list",
        "non-string-caveat",
        "path-in-topic",
        "topic-not-a-slug",
        "multi-line-approach",
        "empty-topic-body",
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


def test_a_reel_on_a_new_problem_creates_a_topic_that_links_to_its_entry(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)

    world.cycle()

    frontmatter, body = read_markdown(tmp_path / "topics" / "slow-permission-prompts.md")
    assert frontmatter == {
        "slug": "slow-permission-prompts",
        "title": "Slow permission prompts",
        "problem": "Claude Code keeps asking for permission on safe commands",
        "approach": "Allowlist read-only commands in settings.json",
        "pinned": False,
        "entries": [SHORTCODE],
        "updated": "2026-10-30",
    }
    assert "Add safe, read-only commands to `permissions.allow`" in body
    assert f"(../entries/{SHORTCODE}.md)" in body
    assert f"entries/{SHORTCODE}.md" in world.kb_files()
    assert "(1 reel, updated 2026-10-30)" in (tmp_path / "index.md").read_text()
    assert (
        "- Claude Code keeps asking for permission on safe commands → "
        "Allowlist read-only commands in settings.json (see topics/slow-permission-prompts.md)"
    ) in (tmp_path / "claude-block.md").read_text()
    assert world.inbox.reactions == [(42, "✅", None)]


def test_a_reel_on_a_known_problem_is_merged_into_the_existing_topic(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)
    world.cycle()

    world.now = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
    world.summarizer.draft = replace(
        DRAFT,
        topic=TopicDecision(
            target=ExistingTopic(slug="slow-permission-prompts"),
            approach="Allowlist read-only commands in project settings",
            body=f"{DRAFT.topic.body}\n\nPrefer `.claude/settings.json` in the project so the allowlist travels with the repo.",
        ),
    )
    world.share(message_id=43, text=OTHER_LINK)
    world.cycle()

    assert world.summarizer.requests[-1].topics == {
        "slow-permission-prompts": "Add safe, read-only commands to `permissions.allow` so they run without a prompt."
    }
    frontmatter, body = read_markdown(tmp_path / "topics" / "slow-permission-prompts.md")
    assert frontmatter == {
        "slug": "slow-permission-prompts",
        "title": "Slow permission prompts",
        "problem": "Claude Code keeps asking for permission on safe commands",
        "approach": "Allowlist read-only commands in project settings",
        "pinned": False,
        "entries": [SHORTCODE, OTHER_SHORTCODE],
        "updated": "2026-11-02",
    }
    assert "so the allowlist travels with the repo" in body
    assert f"(../entries/{SHORTCODE}.md)" in body
    assert f"(../entries/{OTHER_SHORTCODE}.md)" in body


def test_a_merge_may_reorganise_the_topic_as_long_as_every_command_is_kept(tmp_path: Path) -> None:
    write_topic_file(
        tmp_path,
        "slow-permission-prompts",
        reels=1,
        updated="2026-10-01",
        body="Run `claude config list` first.\n\n```json\n{\"permissions\": {\"allow\": [\"Bash(git status)\"]}}\n```",
    )
    topic_path = tmp_path / "topics" / "slow-permission-prompts.md"
    world = make_world(tmp_path)
    world.summarizer.draft = replace(
        DRAFT,
        topic=TopicDecision(
            target=ExistingTopic(slug="slow-permission-prompts"),
            approach="Allowlist read-only commands",
            body="## Allowlist\n\n```\nclaude config list\n```\n\nThen allow "
            '`{"permissions": {"allow": ["Bash(git status)"]}}`.',
        ),
    )
    world.share(message_id=42)

    world.cycle()

    assert world.inbox.reactions == [(42, "✅", None)]
    assert "## Allowlist" in topic_path.read_text()


def test_a_stray_backtick_in_the_topic_does_not_block_merges_into_it(tmp_path: Path) -> None:
    write_topic_file(
        tmp_path,
        "slow-permission-prompts",
        reels=1,
        updated="2026-10-01",
        body="Don`t allowlist everything.\n\nRun `claude config list` to see the current rules.",
    )
    world = make_world(tmp_path)
    world.summarizer.draft = replace(
        DRAFT,
        topic=TopicDecision(
            target=ExistingTopic(slug="slow-permission-prompts"),
            approach="Allowlist read-only commands",
            body="Do not allowlist everything.\n\nCheck the current rules with `claude config list`.",
        ),
    )
    world.share(message_id=42)

    world.cycle()

    assert world.inbox.reactions == [(42, "✅", None)]


def merge_other_reel_into_existing_topic(world: World) -> None:
    world.summarizer.draft = replace(
        DRAFT,
        topic=TopicDecision(
            target=ExistingTopic(slug="slow-permission-prompts"),
            approach="Allowlist read-only commands in project settings",
            body=f"{DRAFT.topic.body}\n\nMerged guidance.",
        ),
    )
    world.share(message_id=43, text=OTHER_LINK)
    world.cycle()


def test_a_user_set_pinned_flag_survives_a_topic_rewrite(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)
    world.cycle()
    topic_path = tmp_path / "topics" / "slow-permission-prompts.md"
    topic_path.write_text(topic_path.read_text().replace("pinned: false", "pinned: true"))

    merge_other_reel_into_existing_topic(world)

    frontmatter, _ = read_markdown(topic_path)
    assert frontmatter["pinned"] is True
    assert frontmatter["entries"] == [SHORTCODE, OTHER_SHORTCODE]


@pytest.mark.parametrize(
    "decision",
    [
        TopicDecision(target=ExistingTopic(slug="no-such-topic"), approach="Something", body="Guidance."),
        replace(DRAFT.topic, body="A rewrite that never saw the existing guidance."),
        TopicDecision(
            target=ExistingTopic(slug="slow-permission-prompts"),
            approach="Allowlist read-only commands",
            body="Add safe, read-only commands to the allowlist so they run without a prompt. "
            "Prefer `.claude/settings.json` in the project.",
        ),
        TopicDecision(
            target=ExistingTopic(slug="slow-permission-prompts"),
            approach="Allowlist read-only commands",
            body="Use `permissions.allow`.",
        ),
    ],
    ids=["existing-topic-missing", "new-topic-already-exists", "merge-drops-a-command", "merge-shrinks-the-topic"],
)
def test_a_topic_decision_that_contradicts_the_kb_is_a_failure(tmp_path: Path, decision: TopicDecision) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)
    world.cycle()
    kb_before = world.kb_files()

    world.summarizer.draft = replace(DRAFT, topic=decision)
    world.share(message_id=43, text=OTHER_LINK)
    world.cycle()

    assert world.kb_files() == kb_before
    [item] = load_state(tmp_path).pending
    assert (item.shortcode, item.attempts) == (OTHER_SHORTCODE, 1)


def test_the_index_lists_every_topic_and_is_given_to_the_summarizer(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    world.share(message_id=42)
    world.cycle()
    merge_other_reel_into_existing_topic(world)

    index = (tmp_path / "index.md").read_text()
    assert (
        "- [Slow permission prompts](topics/slow-permission-prompts.md): "
        "Claude Code keeps asking for permission on safe commands → "
        "Allowlist read-only commands in project settings (2 reels, updated 2026-10-30)"
    ) in index
    assert "[Slow permission prompts](topics/slow-permission-prompts.md)" in world.summarizer.requests[-1].index


def write_topic_file(
    kb_dir: Path, slug: str, *, reels: int, updated: str, pinned: bool = False, body: str | None = None
) -> None:
    path = kb_dir / "topics" / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = "".join(f"- {slug}{n}\n" for n in range(reels))
    path.write_text(
        f"---\nslug: {slug}\ntitle: Title of {slug}\nproblem: Problem of {slug}\napproach: Approach of {slug}\n"
        f"pinned: {str(pinned).lower()}\nentries:\n{entries}updated: '{updated}'\n---\n\n{body or f"Guidance for {slug}."}\n"
    )


def test_the_claude_block_ranks_pinned_then_reel_count_then_recency_and_is_capped(tmp_path: Path) -> None:
    write_topic_file(tmp_path, "pinned-but-rare", reels=1, updated="2026-01-01", pinned=True)
    write_topic_file(tmp_path, "most-reels", reels=5, updated="2026-02-01")
    write_topic_file(tmp_path, "three-reels-older", reels=3, updated="2026-10-01")
    write_topic_file(tmp_path, "three-reels-newer", reels=3, updated="2026-10-20")
    for day in range(1, 14):
        write_topic_file(tmp_path, f"single-{day:02d}", reels=1, updated=f"2026-09-{day:02d}")
    world = make_world(tmp_path)

    world.cycle()

    block = (tmp_path / "claude-block.md").read_text()
    ranked = re.findall(r"^- Problem of (\S+) → Approach of \1 \(see topics/\1\.md\)", block, re.MULTILINE)
    assert ranked == [
        "pinned-but-rare",
        "most-reels",
        "three-reels-newer",
        "three-reels-older",
        *[f"single-{day:02d}" for day in range(13, 2, -1)],
    ]
    assert len(re.findall(r"^- ", block, re.MULTILINE)) == 15
    last_line = block.strip().splitlines()[-1]
    assert "index.md" in last_line and "/ai-kb" in last_line


def test_a_reel_whose_topic_was_written_just_before_a_crash_is_still_added_on_retry(tmp_path: Path) -> None:
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
    frontmatter, _ = read_markdown(tmp_path / "topics" / "slow-permission-prompts.md")
    assert frontmatter["entries"] == [SHORTCODE]


def test_hand_edited_topic_files_are_read_leniently(tmp_path: Path) -> None:
    path = tmp_path / "topics" / "hand-edited.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(
        b"---\r\nslug: hand-edited\r\ntitle: Hand edited\r\nproblem: Odd YAML\r\napproach: Tolerate it\r\n"
        b'pinned: "false"\r\nentries:\r\nupdated: 2026-10-01\r\n---\r\n\r\nGuidance.\r\n'
    )
    write_topic_file(tmp_path, "pinned-one", reels=1, updated="2026-01-01", pinned=True)
    world = make_world(tmp_path)

    world.cycle()

    block = (tmp_path / "claude-block.md").read_text()
    assert block.index("Problem of pinned-one") < block.index("Odd YAML")
    assert "(0 reels, updated 2026-10-01)" in (tmp_path / "index.md").read_text()
