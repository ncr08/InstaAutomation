"""Knowledge-base entries: one Markdown file with YAML frontmatter per reel, written once and never merged."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from instaautomation.ports import EntryDraft, Reel

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EntryListing:
    """What the index and the Claude block show of an entry."""

    shortcode: str
    category: str
    problem: str
    approach: str
    pinned: bool
    date_added: str


def render_entry(reel: Reel, draft: EntryDraft, date_added: str, transcript: str, on_screen_text: str) -> str:
    frontmatter = yaml.safe_dump(
        {
            "source_url": reel.url,
            "shortcode": reel.shortcode,
            "creator": reel.creator,
            "date_added": date_added,
            "category": draft.category,
            "problem": draft.problem,
            "approach": draft.approach,
            # Set to true by hand to keep the entry at the top of the Claude block.
            "pinned": False,
            "tools": draft.tools,
            "tags": draft.tags,
        },
        sort_keys=False,
        allow_unicode=True,
    )
    sections = [
        ("Summary", draft.summary),
        ("The technique", draft.technique),
        ("Step-by-step instructions", _numbered(draft.steps)),
        ("Prerequisites", _bulleted(draft.prerequisites)),
        ("When this is useful", draft.when_useful),
        ("Caveats", _bulleted(draft.caveats)),
    ]
    body = "\n\n".join(f"## {heading}\n\n{text}" for heading, text in sections)
    raw = (
        "<details>\n<summary>Raw transcript and on-screen text</summary>\n\n"
        f"### Transcript\n\n{_fenced(transcript)}\n\n"
        f"### On-screen text\n\n{_fenced(on_screen_text)}\n\n"
        "</details>\n"
    )
    return f"---\n{frontmatter}---\n\n{body}\n\n{raw}"


def load_entries(kb_dir: Path) -> list[EntryListing]:
    entries = []
    for path in sorted((kb_dir / "entries").glob("*.md")):
        try:
            entries.append(_listing(path))
        except (ValueError, KeyError, TypeError, yaml.YAMLError):
            # Entries are hand-editable (e.g. to pin); one broken file must not hide the rest.
            log.warning("skipping unreadable entry %s", path.name, exc_info=True)
    return entries


def _listing(path: Path) -> EntryListing:
    text = path.read_text().replace("\r\n", "\n")
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise ValueError(f"{path} has no frontmatter")
    meta = yaml.safe_load(match.group(1))
    return EntryListing(
        shortcode=path.stem,
        category=str(meta["category"]),
        problem=_one_line(meta, "problem"),
        approach=_one_line(meta, "approach"),
        pinned=meta.get("pinned") is True,
        date_added=str(meta["date_added"]),
    )


def _one_line(meta: dict[str, object], key: str) -> str:
    """The index shows these one per line, however they were edited by hand."""
    value = meta[key]
    if value is None:
        raise ValueError(f"{key} is empty")
    return " ".join(str(value).split())


def _numbered(items: list[str]) -> str:
    return "\n".join(f"{n}. {item}" for n, item in enumerate(items, start=1))


def _bulleted(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _fenced(text: str) -> str:
    longest_run = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest_run + 1)
    return f"{fence}text\n{text}\n{fence}"
