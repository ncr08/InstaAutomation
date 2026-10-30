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
from instaautomation.entry import load_entries
from instaautomation.fakes import FakeCoverMaker, FakeInbox, FakeReelSource, FakeScreenReader, FakeTranscriber, FixedClock
from instaautomation.pipeline import run_cycle
from instaautomation.ports import Message, Ports, Reel

pytestmark = pytest.mark.skipif(os.environ.get("RUN_SMOKE") != "1", reason="live smoke test; set RUN_SMOKE=1")

OWNER_ID = 1001
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


def test_deepseek_summarizes_real_text_into_entries_the_core_accepts(tmp_path: Path) -> None:
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
        cover_maker=FakeCoverMaker(),
        clock=FixedClock(datetime(2026, 10, 30, tzinfo=timezone.utc)),
    )

    run_cycle(ports, tmp_path, owner_id=OWNER_ID)

    for path in [tmp_path / "index.md", tmp_path / "claude-block.md", *sorted((tmp_path / "entries").glob("*.md"))]:
        print(f"\n===== {path.relative_to(tmp_path)} =====\n{path.read_text()}")
    assert [emoji for _, emoji, _ in inbox.reactions] == ["✅", "✅"]
    categories = {entry.shortcode: entry.category for entry in load_entries(tmp_path)}
    assert categories["DSmokePerm1"] == "coding-agents"
    assert categories["DSmokeSilent"] in {"coding-agents", "context-and-memory"}
    assert "Bash(npm run test:*)" in (tmp_path / "entries" / "DSmokePerm1.md").read_text()
    assert "/init" in (tmp_path / "entries" / "DSmokeSilent.md").read_text()
