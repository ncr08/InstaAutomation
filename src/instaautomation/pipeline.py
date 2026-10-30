"""The pipeline core: one cycle turns shared reels into knowledge-base entries."""

import logging
import re
from pathlib import Path

from instaautomation.categories import load_categories
from instaautomation.entry import load_entries, render_entry
from instaautomation.navigation import render_claude_block, render_index
from instaautomation.ports import EntryDraft, Inbox, MessageRef, Ports, SummaryRequest
from instaautomation.state import QueueItem, State, load_state, save_state

REEL_LINK = re.compile(r"https?://(?:www\.)?instagram\.com/(reels?|p)/([A-Za-z0-9_-]+)")
ADDED = "✅"
FAILED = "❌"
MAX_ATTEMPTS = 3

log = logging.getLogger(__name__)


def run_cycle(ports: Ports, kb_dir: Path, *, owner_id: int) -> None:
    state = load_state(kb_dir)
    # Persist the queue before touching any other port: Telegram drops updates after 24 hours.
    already_added = _enqueue(ports.inbox, state, owner_id)
    save_state(kb_dir, state)
    for ref in already_added:
        _react(ports.inbox, ref, ADDED)
    # Read once, before any paid call: a mistake in the owner's file fails the run without costing reels attempts.
    categories = load_categories(kb_dir)
    for item in list(state.pending):
        try:
            category = _process(ports, kb_dir, item, categories)
        except Exception as error:
            item.attempts += 1
            item.last_error = _one_line(error)
            gave_up = item.attempts >= MAX_ATTEMPTS
            if gave_up:
                state.pending.remove(item)
                state.failed.append(item)
            save_state(kb_dir, state)
            if gave_up:
                log.info("failed %s, gave up after %d attempts: %s", item.shortcode, item.attempts, item.last_error)
                _react(ports.inbox, item.ref, FAILED, item.last_error)
            else:
                log.info("failed %s, attempt %d/%d, will retry: %s", item.shortcode, item.attempts, MAX_ATTEMPTS, item.last_error)
        else:
            state.pending.remove(item)
            state.processed.add(item.shortcode)
            save_state(kb_dir, state)
            log.info("processed %s into %s", item.shortcode, category)
            _react(ports.inbox, item.ref, ADDED)
    _regenerate_navigation(kb_dir)


def _regenerate_navigation(kb_dir: Path) -> None:
    """Rebuilt from the entry files every cycle, so hand edits such as pinning show up without a new reel."""
    entries = load_entries(kb_dir)
    if not entries:
        return
    categories = load_categories(kb_dir)
    _write_if_changed(kb_dir / "index.md", render_index(entries, categories))
    _write_if_changed(kb_dir / "claude-block.md", render_claude_block(entries, categories))


def _write_if_changed(path: Path, text: str) -> None:
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def _enqueue(inbox: Inbox, state: State, owner_id: int) -> list[MessageRef]:
    """Queue new reels from the owner; returns duplicate shares of already-added reels."""
    already_added = []
    messages = inbox.fetch_messages(state.offset)
    for message in messages:
        if message.sender_id != owner_id:
            continue
        match = REEL_LINK.search(message.text)
        if not match:
            continue
        kind, shortcode = match.groups()
        if shortcode in state.processed:
            log.info("skipped %s: already added", shortcode)
            already_added.append(message.ref)
            continue
        if any(item.shortcode == shortcode for item in state.pending):
            # Already queued: the original message gets the reaction once it is processed.
            log.info("skipped %s: already queued", shortcode)
            continue
        # A resent failed reel gets a fresh set of attempts.
        state.failed = [item for item in state.failed if item.shortcode != shortcode]
        url = f"https://www.instagram.com/{kind}/{shortcode}/"
        state.pending.append(QueueItem(shortcode=shortcode, url=url, ref=message.ref))
        log.info("queued %s", shortcode)
    if messages:
        state.offset = max(message.update_id for message in messages) + 1
    return already_added


def _react(inbox: Inbox, ref: MessageRef, emoji: str, reason: str | None = None) -> None:
    """Best effort: state is already saved, so a rejected reaction must not stop the cycle."""
    try:
        inbox.react(ref, emoji, reason)
    except Exception:
        log.warning("could not react %s to message %s", emoji, ref.message_id, exc_info=True)


def _process(ports: Ports, kb_dir: Path, item: QueueItem, categories: dict[str, str]) -> str:
    """Writes the reel's entry; returns the category it was filed under."""
    reel = ports.reel_source.fetch(item.url)
    transcript = ports.transcriber.transcribe(reel.video_path)
    on_screen_text = ports.screen_reader.read(reel.video_path)
    draft = ports.summarizer.summarize(
        SummaryRequest(
            transcript=transcript,
            caption=reel.caption,
            on_screen_text=on_screen_text,
            creator=reel.creator,
            categories=categories,
        )
    )
    _check_draft(draft, categories)
    date_added = ports.clock.now().date().isoformat()
    entry_path = kb_dir / "entries" / f"{reel.shortcode}.md"
    entry_path.parent.mkdir(parents=True, exist_ok=True)
    entry_path.write_text(render_entry(reel, draft, date_added, transcript, on_screen_text))
    return draft.category


class MalformedSummary(ValueError):
    """The summarizer returned something that can't safely become a knowledge-base entry."""


def _check_draft(draft: EntryDraft, categories: dict[str, str]) -> None:
    for name in ("summary", "technique", "when_useful"):
        if not _is_text(getattr(draft, name)):
            raise MalformedSummary(f"{name} must be non-empty text")
    # The index and Claude block show these one line per entry.
    for name in ("problem", "approach"):
        value = getattr(draft, name)
        if not _is_text(value) or "\n" in value.strip():
            raise MalformedSummary(f"{name} must be a single line of text")
    for name in ("steps", "prerequisites", "caveats", "tools", "tags"):
        value = getattr(draft, name)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise MalformedSummary(f"{name} must be a list of text")
    if not draft.steps:
        raise MalformedSummary("steps must not be empty")
    if draft.category not in categories:
        raise MalformedSummary(f"not one of the categories: {str(draft.category)[:60]!r}")


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _one_line(error: Exception) -> str:
    text = " ".join(f"{type(error).__name__}: {error}".split())
    return text[:200]
