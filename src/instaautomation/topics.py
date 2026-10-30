"""Topic files: one problem each, merging the guidance of every reel routed to it."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

SOURCES_HEADING = "## Source entries"


@dataclass
class Topic:
    slug: str
    title: str
    problem: str
    approach: str
    pinned: bool
    entries: list[str]
    updated: str
    body: str


def load_topics(kb_dir: Path) -> dict[str, Topic]:
    return {topic.slug: topic for topic in map(_parse, sorted((kb_dir / "topics").glob("*.md")))}


def _parse(path: Path) -> Topic:
    # Topic files are hand-editable (e.g. to pin), so read them leniently.
    text = path.read_text().replace("\r\n", "\n")
    match = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.DOTALL)
    if not match:
        raise ValueError(f"{path} has no frontmatter")
    meta = yaml.safe_load(match.group(1))
    # The source links are regenerated from `entries` on every write, so they aren't part of the guidance.
    guidance, heading, _ = match.group(2).rpartition(f"\n{SOURCES_HEADING}\n")
    return Topic(
        slug=str(meta["slug"]),
        title=str(meta["title"]),
        problem=str(meta["problem"]),
        approach=str(meta["approach"]),
        pinned=meta.get("pinned") is True,
        entries=[str(shortcode) for shortcode in meta.get("entries") or []],
        updated=str(meta["updated"]),
        body=(guidance if heading else match.group(2)).strip(),
    )


def write_topic(kb_dir: Path, topic: Topic) -> None:
    path = kb_dir / "topics" / f"{topic.slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render(topic))


def _render(topic: Topic) -> str:
    frontmatter = yaml.safe_dump(
        {
            "slug": topic.slug,
            "title": topic.title,
            "problem": topic.problem,
            "approach": topic.approach,
            "pinned": topic.pinned,
            "entries": topic.entries,
            "updated": topic.updated,
        },
        sort_keys=False,
        allow_unicode=True,
    )
    links = "\n".join(f"- [{shortcode}](../entries/{shortcode}.md)" for shortcode in topic.entries)
    return f"---\n{frontmatter}---\n\n{topic.body.strip()}\n\n{SOURCES_HEADING}\n\n{links}\n"
