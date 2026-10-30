"""The pipeline core: one cycle turns shared reels into knowledge-base entries."""

import re
from pathlib import Path

from instaautomation.entry import render_entry
from instaautomation.ports import Ports, SummaryRequest

REEL_LINK = re.compile(r"https?://(?:www\.)?instagram\.com/(reels?|p)/([A-Za-z0-9_-]+)")
ADDED = "✅"


def run_cycle(ports: Ports, kb_dir: Path) -> None:
    for message in ports.inbox.fetch_messages():
        match = REEL_LINK.search(message.text)
        if not match:
            continue
        kind, shortcode = match.groups()
        reel = ports.reel_source.fetch(f"https://www.instagram.com/{kind}/{shortcode}/")
        transcript = ports.transcriber.transcribe(reel.video_path)
        on_screen_text = ports.screen_reader.read(reel.video_path)
        draft = ports.summarizer.summarize(
            SummaryRequest(
                transcript=transcript,
                caption=reel.caption,
                on_screen_text=on_screen_text,
                creator=reel.creator,
                index="",
            )
        )
        date_added = ports.clock.now().date().isoformat()
        entry_path = kb_dir / "entries" / f"{reel.shortcode}.md"
        entry_path.parent.mkdir(parents=True, exist_ok=True)
        entry_path.write_text(render_entry(reel, draft, date_added, transcript, on_screen_text))
        ports.inbox.react(message, ADDED)
