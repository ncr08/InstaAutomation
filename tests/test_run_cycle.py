import re
from datetime import datetime, timezone
from pathlib import Path

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


def test_owner_shares_a_reel_and_one_cycle_writes_an_entry_and_reacts_ok(tmp_path: Path) -> None:
    message = Message(
        message_id=42,
        chat_id=OWNER_ID,
        sender_id=OWNER_ID,
        text="https://www.instagram.com/reel/DAbc123XyZ/?igsh=MWQ1ZGUxMzBkMA==",
    )
    inbox = FakeInbox([message])
    ports = Ports(
        inbox=inbox,
        reel_source=FakeReelSource(
            [
                Reel(
                    url="https://www.instagram.com/reel/DAbc123XyZ/",
                    shortcode="DAbc123XyZ",
                    creator="aitipsdaily",
                    caption="Stop clicking allow on every prompt",
                    video_path=VIDEO,
                )
            ]
        ),
        transcriber=FakeTranscriber({VIDEO: "So here is how you stop the permission prompts."}),
        screen_reader=FakeScreenReader({VIDEO: '"permissions": {"allow": ["Bash(git status)"]}'}),
        summarizer=FakeSummarizer(
            EntryDraft(
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
        ),
        clock=FixedClock(datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)),
    )

    run_cycle(ports, tmp_path)

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

    assert inbox.reactions == [(42, "✅")]
