"""The pipeline core: one cycle turns shared reels into knowledge-base entries."""

import logging
import re
from pathlib import Path

from instaautomation.entry import render_entry
from instaautomation.navigation import render_claude_block, render_index
from instaautomation.ports import EntryDraft, ExistingTopic, Inbox, MessageRef, NewTopic, Ports, SummaryRequest, TopicDecision
from instaautomation.state import QueueItem, State, load_state, save_state
from instaautomation.topics import Topic, load_topics, write_topic

REEL_LINK = re.compile(r"https?://(?:www\.)?instagram\.com/(reels?|p)/([A-Za-z0-9_-]+)")
ADDED = "✅"
FAILED = "❌"
MAX_ATTEMPTS = 3
TOPIC_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# The language tag after the opening fence isn't code.
FENCED_CODE = re.compile(r"^ *(`{3,}|~{3,})[^\n]*\n(.*?)^ *\1[`~]*[ \t]*$", re.DOTALL | re.MULTILINE)
# Kept to one line, so a stray backtick (an apostrophe typed as `) can't pair with code paragraphs away.
INLINE_CODE = re.compile(r"(?<!`)(`+)(?!`)([^\n]+?)(?<!`)\1(?!`)")
# A merged topic body shorter than this share of the old one has lost guidance.
MIN_MERGED_LENGTH_RATIO = 0.7

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
    _regenerate_navigation(kb_dir)


def _regenerate_navigation(kb_dir: Path) -> None:
    """Rebuilt from the topic files every cycle, so hand edits such as pinning show up without a new reel."""
    topics = load_topics(kb_dir).values()
    if not topics:
        return
    _write_if_changed(kb_dir / "index.md", render_index(topics))
    _write_if_changed(kb_dir / "claude-block.md", render_claude_block(topics))


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
    # Read before any paid call, so an unreadable topic file costs nothing.
    topics = load_topics(kb_dir)
    reel = ports.reel_source.fetch(item.url)
    transcript = ports.transcriber.transcribe(reel.video_path)
    on_screen_text = ports.screen_reader.read(reel.video_path)
    draft = ports.summarizer.summarize(
        SummaryRequest(
            transcript=transcript,
            caption=reel.caption,
            on_screen_text=on_screen_text,
            creator=reel.creator,
            index=render_index(topics.values()),
            topics={slug: topic.body for slug, topic in topics.items()},
        )
    )
    _check_draft(draft, topics, reel.shortcode)
    date_added = ports.clock.now().date().isoformat()
    entry_path = kb_dir / "entries" / f"{reel.shortcode}.md"
    entry_path.parent.mkdir(parents=True, exist_ok=True)
    entry_path.write_text(render_entry(reel, draft, date_added, transcript, on_screen_text))
    write_topic(kb_dir, _routed_topic(draft.topic, topics, reel.shortcode, date_added))


def _routed_topic(decision: TopicDecision, topics: dict[str, Topic], shortcode: str, date: str) -> Topic:
    target = decision.target
    if isinstance(target, NewTopic):
        # Only already on disk when retrying after a crash that followed this reel's own topic write.
        previous = topics.get(target.slug)
        topic = Topic(
            slug=target.slug,
            title=target.title,
            problem=target.problem,
            approach=decision.approach,
            pinned=previous.pinned if previous else False,
            entries=previous.entries if previous else [],
            updated=date,
            body=decision.body,
        )
    else:
        # Title, problem and the user's pinned flag stay as they are on disk.
        topic = topics[target.slug]
        topic.approach = decision.approach
        topic.body = decision.body
        topic.updated = date
    if shortcode not in topic.entries:
        topic.entries.append(shortcode)
    return topic


class MalformedSummary(ValueError):
    """The summarizer returned something that can't safely become a knowledge-base entry."""


def _check_draft(draft: EntryDraft, topics: dict[str, Topic], shortcode: str) -> None:
    for name in ("summary", "technique", "when_useful"):
        if not _is_text(getattr(draft, name)):
            raise MalformedSummary(f"{name} must be non-empty text")
    for name in ("steps", "prerequisites", "caveats", "tools", "tags"):
        value = getattr(draft, name)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise MalformedSummary(f"{name} must be a list of text")
    if not draft.steps:
        raise MalformedSummary("steps must not be empty")
    _check_decision(draft.topic, topics, shortcode)


def _check_decision(decision: TopicDecision, topics: dict[str, Topic], shortcode: str) -> None:
    target = decision.target
    if not TOPIC_SLUG.fullmatch(target.slug):
        raise MalformedSummary(f"topic is not a slug: {target.slug!r}")
    # The index and Claude block show these one line per topic.
    one_liners = {"approach": decision.approach}
    if isinstance(target, NewTopic):
        one_liners |= {"title": target.title, "problem": target.problem}
    for name, value in one_liners.items():
        if not _is_text(value) or "\n" in value.strip():
            raise MalformedSummary(f"topic {name} must be a single line of text")
    if not _is_text(decision.body):
        raise MalformedSummary("topic body must be non-empty text")
    if isinstance(target, ExistingTopic):
        if target.slug not in topics:
            raise MalformedSummary(f"existing topic does not exist: {target.slug}")
        _check_merge_keeps_guidance(topics[target.slug].body, decision.body)
    if isinstance(target, NewTopic) and target.slug in topics and shortcode not in topics[target.slug].entries:
        raise MalformedSummary(f"new topic already exists: {target.slug}")


def _check_merge_keeps_guidance(old: str, new: str) -> None:
    """A merge replaces the topic body wholesale, so catch rewrites that drop earlier reels' guidance.

    Commands and config are the most valuable part and survive any rewording, so each must still be there;
    a body much shorter than before has lost prose. Small prose losses still get through.
    """
    missing = [snippet for snippet in _code_snippets(old) if snippet not in new]
    if missing:
        raise MalformedSummary(f"topic merge dropped code from {len(missing)} place(s), e.g. {missing[0][:60]!r}")
    if len(new.strip()) < MIN_MERGED_LENGTH_RATIO * len(old.strip()):
        raise MalformedSummary(f"topic merge shrank the topic from {len(old.strip())} to {len(new.strip())} characters")


def _code_snippets(markdown: str) -> list[str]:
    """Inline code spans and the lines of fenced code blocks."""
    blocks = [match.group(2) for match in FENCED_CODE.finditer(markdown)]
    lines = [line.strip() for block in blocks for line in block.splitlines() if line.strip()]
    prose = FENCED_CODE.sub("", markdown)
    spans = [match.group(2).strip() for match in INLINE_CODE.finditer(prose) if match.group(2).strip()]
    return lines + spans


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _one_line(error: Exception) -> str:
    text = " ".join(f"{type(error).__name__}: {error}".split())
    return text[:200]
