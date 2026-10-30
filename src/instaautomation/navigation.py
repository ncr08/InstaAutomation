"""The index and the Claude block: generated views over the topics, rebuilt every cycle."""

from collections.abc import Iterable

from instaautomation.topics import Topic

CLAUDE_BLOCK_LIMIT = 15


def render_index(topics: Iterable[Topic]) -> str:
    lines = [
        f"- [{topic.title}](topics/{topic.slug}.md): {topic.problem} → {topic.approach} "
        f"({_reel_count_label(topic)}, updated {topic.updated})"
        for topic in sorted(topics, key=lambda topic: topic.title.casefold())
    ]
    return "# Index\n\n" + "\n".join(lines) + "\n"


def _reel_count_label(topic: Topic) -> str:
    count = len(topic.entries)
    return f"{count} reel" if count == 1 else f"{count} reels"


def render_claude_block(topics: Iterable[Topic]) -> str:
    ranked = sorted(topics, key=lambda topic: topic.slug)
    # Stable sorts from least to most significant key: pinned first, then most reels, then most recently updated.
    ranked.sort(key=lambda topic: topic.updated, reverse=True)
    ranked.sort(key=lambda topic: len(topic.entries), reverse=True)
    ranked.sort(key=lambda topic: topic.pinned, reverse=True)
    lines = [
        f"- {topic.problem} → {topic.approach} (see topics/{topic.slug}.md)" for topic in ranked[:CLAUDE_BLOCK_LIMIT]
    ]
    return (
        "# AI knowledge base: techniques from saved reels\n\n"
        "When one of these problems comes up, suggest the approach:\n\n"
        + "\n".join(lines)
        + "\n\nPaths are relative to the folder of this file. Every topic is listed in index.md there; "
        "use `/ai-kb <question>` for detailed step-by-step instructions.\n"
    )
