"""Manual smoke test for the DeepSeek summarizer, driven through a whole cycle so real replies must pass the core's
checks. Needs a DeepSeek key; CI never runs it.

    set -a; source .env; set +a
    RUN_SMOKE=1 uv run pytest tests/smoke/test_live_summarizer.py -s
"""

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from instaautomation.deepseek import DeepSeekSummarizer
from instaautomation.fakes import FakeInbox, FakeReelSource, FakeScreenReader, FakeTranscriber, FixedClock
from instaautomation.pipeline import run_cycle
from instaautomation.ports import Message, Ports, Reel
from instaautomation.topics import Topic, load_topics, write_topic

pytestmark = pytest.mark.skipif(os.environ.get("RUN_SMOKE") != "1", reason="live smoke test; set RUN_SMOKE=1")

OWNER_ID = 1001
EXISTING_GUIDANCE = "Approve a command once with **Always allow** so Claude Code stops asking for it."
# (shortcode, transcript, on-screen text as OCR reads it, caption)
REELS = [
    (
        "DSmokePerm1",
        "Stop clicking approve on every single command. Open your settings file and add the allowlist. "
        "Every command in there runs without asking.",
        'Stop clicking approve\n.claude/settings.json\n"permissions": {"allow": ["Bash(npm run test:*)", "Bash(git status)"]}',
        "Claude Code tip: no more permission spam 🔥",
    ),
    (
        "DSmokeSilent",
        "",
        "Claude forgets your conventions?\nRun /init\nIt writes CLAUDE.md\nAdd: Use pnpm, not npm",
        "Silent tip: make Claude remember how your project works",
    ),
]


def test_deepseek_summarizes_real_text_into_entries_and_topics_the_core_accepts(tmp_path: Path) -> None:
    write_topic(
        tmp_path,
        Topic(
            slug="permission-prompts",
            title="Permission prompts",
            problem="Claude Code keeps asking permission to run the same commands",
            approach="approve once with Always allow",
            pinned=False,
            entries=["DOlderReel1"],
            updated="2026-10-01",
            body=EXISTING_GUIDANCE,
        ),
    )
    inbox = FakeInbox(
        [
            Message(update_id=n, message_id=n, chat_id=OWNER_ID, sender_id=OWNER_ID, text=f"https://www.instagram.com/reel/{shortcode}/")
            for n, (shortcode, *_) in enumerate(REELS, start=1)
        ]
    )
    videos = {shortcode: Path(f"/videos/{shortcode}.mp4") for shortcode, *_ in REELS}
    ports = Ports(
        inbox=inbox,
        reel_source=FakeReelSource(
            [
                Reel(url=f"https://www.instagram.com/reel/{shortcode}/", shortcode=shortcode, creator="aitipsdaily", caption=caption, video_path=videos[shortcode])
                for shortcode, _, _, caption in REELS
            ]
        ),
        transcriber=FakeTranscriber({videos[shortcode]: transcript for shortcode, transcript, _, _ in REELS}),
        screen_reader=FakeScreenReader({videos[shortcode]: text for shortcode, _, text, _ in REELS}),
        summarizer=DeepSeekSummarizer.from_env(),
        clock=FixedClock(datetime(2026, 10, 30, tzinfo=timezone.utc)),
    )

    run_cycle(ports, tmp_path, owner_id=OWNER_ID)

    for path in sorted(tmp_path.rglob("*.md")):
        print(f"\n===== {path.relative_to(tmp_path)} =====\n{path.read_text()}")
    print(inbox.reactions)
    assert [emoji for _, emoji, _ in inbox.reactions] == ["✅", "✅"]
    topics = load_topics(tmp_path)
    # The allowlist reel is on the same problem, so it must be merged in without losing the earlier guidance.
    assert topics["permission-prompts"].entries == ["DOlderReel1", "DSmokePerm1"]
    assert "always allow" in topics["permission-prompts"].body.lower()
    assert "Bash(npm run test:*)" in (tmp_path / "entries" / "DSmokePerm1.md").read_text()
    # The silent reel is on a different problem, so it gets a topic of its own.
    [new_topic] = [topic for slug, topic in topics.items() if slug != "permission-prompts"]
    assert new_topic.entries == ["DSmokeSilent"]
    assert "/init" in (tmp_path / "entries" / "DSmokeSilent.md").read_text()


FULL_KB_PROBLEMS = [
    "Image prompts come out generic",
    "API bills are unpredictable",
    "Local models run too slowly",
    "Meeting notes take too long to write",
    "Spreadsheets need manual cleanup",
    "Slide decks take hours to build",
    "Emails pile up unanswered",
    "Voice cloning sounds robotic",
    "Translations lose the tone",
]


def test_in_a_full_kb_a_reel_on_a_new_problem_goes_to_unsorted(tmp_path: Path) -> None:
    for n, problem in enumerate(FULL_KB_PROBLEMS):
        write_topic(
            tmp_path,
            Topic(
                slug=f"topic-{n}",
                title=problem,
                problem=problem,
                approach="see the topic",
                pinned=False,
                entries=[f"DOld{n}"],
                updated="2026-10-01",
                body=f"Guidance about: {problem.lower()}.",
            ),
        )
    shortcode, transcript, on_screen_text, caption = REELS[1]
    video = Path(f"/videos/{shortcode}.mp4")
    inbox = FakeInbox(
        [Message(update_id=1, message_id=1, chat_id=OWNER_ID, sender_id=OWNER_ID, text=f"https://www.instagram.com/reel/{shortcode}/")]
    )
    ports = Ports(
        inbox=inbox,
        reel_source=FakeReelSource(
            [Reel(url=f"https://www.instagram.com/reel/{shortcode}/", shortcode=shortcode, creator="aitipsdaily", caption=caption, video_path=video)]
        ),
        transcriber=FakeTranscriber({video: transcript}),
        screen_reader=FakeScreenReader({video: on_screen_text}),
        summarizer=DeepSeekSummarizer.from_env(),
        clock=FixedClock(datetime(2026, 10, 30, tzinfo=timezone.utc)),
    )

    run_cycle(ports, tmp_path, owner_id=OWNER_ID)

    print((tmp_path / "topics" / "unsorted.md").read_text())
    assert inbox.reactions == [(1, "✅", None)]
    assert load_topics(tmp_path)["unsorted"].entries == [shortcode]
