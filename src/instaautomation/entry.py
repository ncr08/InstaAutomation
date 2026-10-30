"""Rendering of a knowledge-base entry as Markdown with YAML frontmatter."""

import re

import yaml

from instaautomation.ports import EntryDraft, Reel


def render_entry(reel: Reel, draft: EntryDraft, date_added: str, transcript: str, on_screen_text: str) -> str:
    frontmatter = yaml.safe_dump(
        {
            "source_url": reel.url,
            "shortcode": reel.shortcode,
            "creator": reel.creator,
            "date_added": date_added,
            "topic": draft.topic.target.slug,
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


def _numbered(items: list[str]) -> str:
    return "\n".join(f"{n}. {item}" for n, item in enumerate(items, start=1))


def _bulleted(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _fenced(text: str) -> str:
    longest_run = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest_run + 1)
    return f"{fence}text\n{text}\n{fence}"
