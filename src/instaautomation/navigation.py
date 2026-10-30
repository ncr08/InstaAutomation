"""The index and the Claude block: generated views over the entries, rebuilt every cycle."""

from collections.abc import Iterable

from instaautomation.categories import OTHER, category_name
from instaautomation.entry import EntryListing

CLAUDE_BLOCK_LIMIT = 15


def render_index(entries: Iterable[EntryListing], categories: dict[str, str]) -> str:
    sections = []
    for slug, members in by_category(entries, categories).items():
        lines = "\n".join(
            f"- {_problem_to_approach(entry)} ([{entry.shortcode}](entries/{entry.shortcode}.md), {entry.date_added})"
            for entry in members
        )
        description = f"{categories[slug]}\n\n" if categories[slug] else ""
        sections.append(f"## {category_name(slug)}\n\n{description}{lines}\n")
    return "# Index\n\n" + "\n".join(sections)


def render_claude_block(entries: Iterable[EntryListing], categories: dict[str, str]) -> str:
    grouped = by_category(entries, categories)
    ranked = newest_first(entry for members in grouped.values() for entry in members if entry.pinned)
    # Then round by round, the newest not-yet-listed entry of each category, so every category gets a look-in.
    queues = [[entry for entry in members if not entry.pinned] for members in grouped.values()]
    while any(queues):
        ranked += [queue.pop(0) for queue in queues if queue]
    lines = [f"- {_problem_to_approach(entry)} (see entries/{entry.shortcode}.md)" for entry in ranked[:CLAUDE_BLOCK_LIMIT]]
    return (
        "# AI knowledge base: techniques from saved reels\n\n"
        "When one of these problems comes up, suggest the approach:\n\n"
        + "\n".join(lines)
        + "\n\nPaths are relative to the folder of this file. Every entry is listed by category in index.md there; "
        "use `/ai-kb <question>` for detailed step-by-step instructions.\n"
    )


def _problem_to_approach(entry: EntryListing) -> str:
    return f"{entry.problem} → {entry.approach}"


def by_category(entries: Iterable[EntryListing], categories: dict[str, str]) -> dict[str, list[EntryListing]]:
    """Non-empty categories in the owner's order, each newest first; entries of unlisted categories go to Other."""
    grouped: dict[str, list[EntryListing]] = {slug: [] for slug in categories}
    for entry in entries:
        grouped[filed_under(entry, categories)].append(entry)
    return {slug: newest_first(members) for slug, members in grouped.items() if members}


def filed_under(entry: EntryListing, categories: dict[str, str]) -> str:
    """The entry's category, or Other once the owner has taken its category off the list."""
    return entry.category if entry.category in categories else OTHER


def pinned_then_newest(entries: Iterable[EntryListing]) -> list[EntryListing]:
    entries = list(entries)
    return newest_first(entry for entry in entries if entry.pinned) + newest_first(entry for entry in entries if not entry.pinned)


def newest_first(entries: Iterable[EntryListing]) -> list[EntryListing]:
    # Dates are only days, so ties are common; the shortcode makes the order stable.
    return sorted(entries, key=lambda entry: (entry.date_added, entry.shortcode), reverse=True)
