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


@dataclass(frozen=True)
class Entry:
    """An entry file in full, as the frontend and the cover backfill read it."""

    listing: EntryListing
    source_url: str
    creator: str
    tools: list[str]
    tags: list[str]
    body: str
    """The Markdown after the frontmatter."""

    @property
    def shortcode(self) -> str:
        return self.listing.shortcode

    def sections(self) -> dict[str, str]:
        """Each `## ` section's Markdown by heading, in file order, without the raw transcript block."""
        written = self.body.split("\n<details>", 1)[0]
        parts = re.split(r"^## (.+)\n", written, flags=re.MULTILINE)
        return {heading.strip(): text.strip() for heading, text in zip(parts[1::2], parts[2::2])}

    def raw_text(self, heading: str) -> str:
        """The fenced text under a `### ` heading of the raw block, such as Transcript or On-screen text."""
        match = re.search(rf"^### {re.escape(heading)}\n\n(`{{3,}})text\n(.*?)\n\1$", self.body, re.DOTALL | re.MULTILINE)
        return match.group(2) if match else ""


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


def entry_path(kb_dir: Path, shortcode: str) -> Path:
    return kb_dir / "entries" / f"{shortcode}.md"


def cover_path(kb_dir: Path, shortcode: str) -> Path:
    """The cover sits next to its entry; whether an entry has one is whether this file exists."""
    return kb_dir / "entries" / f"{shortcode}.jpg"


def load_entries(kb_dir: Path) -> list[EntryListing]:
    return [entry.listing for entry in read_entries(kb_dir)]


def read_entries(kb_dir: Path) -> list[Entry]:
    entries = []
    for path in sorted((kb_dir / "entries").glob("*.md")):
        try:
            entries.append(_read(path))
        except (ValueError, KeyError, TypeError, yaml.YAMLError):
            # Entries are hand-editable (e.g. to pin); one broken file must not hide the rest.
            log.warning("skipping unreadable entry %s", path.name, exc_info=True)
    return entries


def _read(path: Path) -> Entry:
    text = path.read_text().replace("\r\n", "\n")
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise ValueError(f"{path} has no frontmatter")
    meta = yaml.safe_load(match.group(1))
    listing = EntryListing(
        shortcode=path.stem,
        category=str(meta["category"]),
        problem=_one_line(meta, "problem"),
        approach=_one_line(meta, "approach"),
        pinned=meta.get("pinned") is True,
        date_added=str(meta["date_added"]),
    )
    return Entry(
        listing=listing,
        source_url=str(meta.get("source_url") or ""),
        creator=str(meta.get("creator") or ""),
        tools=_texts(meta.get("tools")),
        tags=_texts(meta.get("tags")),
        body=text[match.end() :],
    )


def _texts(value: object) -> list[str]:
    """A hand-edited list may have gone missing or become a single word."""
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return [str(value)] if value else []


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
