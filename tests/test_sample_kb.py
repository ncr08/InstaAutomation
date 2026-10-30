"""The hand-written sample knowledge base for checking /ai-kb by hand (see skills/ai-kb/SKILL.md, --kb)."""

from pathlib import Path

from instaautomation.categories import load_categories
from instaautomation.entry import load_entries
from instaautomation.navigation import render_claude_block, render_index

SAMPLE_KB = Path(__file__).resolve().parent / "fixtures" / "sample-kb"


def test_sample_kb_is_what_a_cycle_would_have_written() -> None:
    entries = load_entries(SAMPLE_KB)
    categories = load_categories(SAMPLE_KB)

    assert len(entries) == len(list((SAMPLE_KB / "entries").glob("*.md"))) == 4
    assert (SAMPLE_KB / "index.md").read_text() == render_index(entries, categories)
    assert (SAMPLE_KB / "claude-block.md").read_text() == render_claude_block(entries, categories)
