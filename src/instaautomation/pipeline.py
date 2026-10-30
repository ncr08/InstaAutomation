"""The pipeline core: one cycle turns shared reels into knowledge-base entries."""

import logging
import re
from pathlib import Path

from instaautomation.entry import render_entry
from instaautomation.ports import EntryDraft, Inbox, MessageRef, Ports, SummaryRequest
from instaautomation.state import QueueItem, State, load_state, save_state

REEL_LINK = re.compile(r"https?://(?:www\.)?instagram\.com/(reels?|p)/([A-Za-z0-9_-]+)")
ADDED = "✅"
FAILED = "❌"
MAX_ATTEMPTS = 3
TOPIC_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

log = logging.getLogger(__name__)


def run_cycle(ports: Ports, kb_dir: Path, *, owner_id: int) -> None:
    state = load_state(kb_dir)
    # Persist the queue before touching any other port: Telegram drops updates after 24 hours.
    already_added = _enqueue(ports.inbox, state, owner_id)
    save_state(kb_dir, state)
    for ref in already_added:
        _react(ports.inbox, ref, ADDED)
    for item in list(state.pending):
        try:
            _process(ports, kb_dir, item)
        except Exception as error:
            item.attempts += 1
            item.last_error = _one_line(error)
            gave_up = item.attempts >= MAX_ATTEMPTS
            if gave_up:
                state.pending.remove(item)
                state.failed.append(item)
            save_state(kb_dir, state)
            if gave_up:
                _react(ports.inbox, item.ref, FAILED, item.last_error)
        else:
            state.pending.remove(item)
            state.processed.add(item.shortcode)
            save_state(kb_dir, state)
            _react(ports.inbox, item.ref, ADDED)


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
            already_added.append(message.ref)
            continue
        if any(item.shortcode == shortcode for item in state.pending):
            # Already queued: the original message gets the reaction once it is processed.
            continue
        # A resent failed reel gets a fresh set of attempts.
        state.failed = [item for item in state.failed if item.shortcode != shortcode]
        url = f"https://www.instagram.com/{kind}/{shortcode}/"
        state.pending.append(QueueItem(shortcode=shortcode, url=url, ref=message.ref))
    if messages:
        state.offset = max(message.update_id for message in messages) + 1
    return already_added


def _react(inbox: Inbox, ref: MessageRef, emoji: str, reason: str | None = None) -> None:
    """Best effort: state is already saved, so a rejected reaction must not stop the cycle."""
    try:
        inbox.react(ref, emoji, reason)
    except Exception:
        log.warning("could not react %s to message %s", emoji, ref.message_id, exc_info=True)


def _process(ports: Ports, kb_dir: Path, item: QueueItem) -> None:
    reel = ports.reel_source.fetch(item.url)
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
    _check_draft(draft)
    date_added = ports.clock.now().date().isoformat()
    entry_path = kb_dir / "entries" / f"{reel.shortcode}.md"
    entry_path.parent.mkdir(parents=True, exist_ok=True)
    entry_path.write_text(render_entry(reel, draft, date_added, transcript, on_screen_text))


class MalformedSummary(ValueError):
    """The summarizer returned something that can't safely become a knowledge-base entry."""


def _check_draft(draft: EntryDraft) -> None:
    for name in ("summary", "technique", "when_useful", "topic"):
        value = getattr(draft, name)
        if not isinstance(value, str) or not value.strip():
            raise MalformedSummary(f"{name} must be non-empty text")
    for name in ("steps", "prerequisites", "caveats", "tools", "tags"):
        value = getattr(draft, name)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise MalformedSummary(f"{name} must be a list of text")
    if not draft.steps:
        raise MalformedSummary("steps must not be empty")
    if not TOPIC_SLUG.fullmatch(draft.topic):
        raise MalformedSummary(f"topic is not a slug: {draft.topic!r}")


def _one_line(error: Exception) -> str:
    text = " ".join(f"{type(error).__name__}: {error}".split())
    return text[:200]
