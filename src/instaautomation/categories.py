"""Categories: the owner's fixed list that every entry is filed under, kept in the knowledge base to be edited by hand."""

import re
from pathlib import Path

import yaml

CATEGORIES_FILE = "categories.yml"
OTHER = "other"
OTHER_DESCRIPTION = "Anything that fits no other category"
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

DEFAULT_CATEGORIES = """\
# Every reel's entry is filed under one of these categories. Edit freely: the slug on the left (lowercase, words
# joined by hyphens) and a description that tells the summarizer what belongs there. Order is the order in the
# index. Existing entries keep their category; one that is no longer listed shows up under Other.
# "other" is always available, even if it's not listed.
coding-agents: Claude Code, Cursor, Codex and other coding agents - setup, settings, permissions, hooks, skills, workflows
context-and-memory: CLAUDE.md, project memory, context windows and keeping an assistant on track
prompting: Writing better prompts and instructions for any model
agents-and-automation: Building agents, MCP servers, integrations and automated workflows
models-and-costs: Choosing models, running local models, pricing and limits
content-creation: Images, video, voice and design with AI
writing-and-research: Writing, summarising, research and learning with AI
productivity: Email, notes, meetings, documents and everyday work with AI
new-tools: New AI tools and apps worth trying
other: Anything that fits no other category
"""


def load_categories(kb_dir: Path) -> dict[str, str]:
    """Slug to description in the owner's order, `other` last; writes the defaults on first use."""
    path = kb_dir / CATEGORIES_FILE
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_CATEGORIES)
    listed = yaml.safe_load(path.read_text()) or {}
    if not isinstance(listed, dict):
        raise ValueError(f"{path} must map each category slug to a description")
    categories = {}
    for slug, description in listed.items():
        if not isinstance(slug, str) or not SLUG.fullmatch(slug):
            raise ValueError(f"{path}: category is not a lowercase-hyphenated slug: {slug!r}")
        categories[slug] = str(description or "").strip()
    other = categories.pop(OTHER, None) or OTHER_DESCRIPTION
    return categories | {OTHER: other}


def category_name(slug: str) -> str:
    return slug.replace("-", " ").capitalize()
