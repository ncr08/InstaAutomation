"""The frontend: a static, read-only site built from the knowledge base and opened from a bookmark, no server needed."""

import json
import os
import zlib
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path

from markdown_it import MarkdownIt

from instaautomation.categories import category_name, read_categories
from instaautomation.entry import Entry, cover_path, read_entries
from instaautomation.navigation import by_category, filed_under, pinned_then_newest
from instaautomation.ports import Clock, CycleRun, CycleRuns
from instaautomation.state import STATE_FILE, QueueItem, load_state

SECTIONS_SEARCHED = {"summary": "Summary", "technique": "The technique", "steps": "Step-by-step instructions"}
LAST_UPDATED = ".last-updated"
"""In the site folder: when the knowledge base was last pulled successfully, for the banner after a failed pull."""

# No raw HTML: entry text is written by a model from whatever a stranger put in a caption.
_markdown = MarkdownIt("commonmark", {"html": False})


@dataclass(frozen=True)
class _Links:
    """Relative links, so the site works opened straight from disk; entry pages sit one folder down."""

    root: str
    covers: str
    """The knowledge base's entries folder, relative to the site folder: covers are linked, not copied."""

    def page(self, name: str) -> str:
        return f"{self.root}{name}.html"

    def entry(self, shortcode: str) -> str:
        return f"{self.root}entry/{shortcode}.html"

    def cover(self, shortcode: str) -> str:
        return f"{self.root}{self.covers}/{shortcode}.jpg"


def build_site(kb_dir: Path, out_dir: Path, *, update_failure: str | None, cycle_runs: CycleRuns, clock: Clock) -> None:
    """Writes the library, status and entry pages into out_dir; never writes to the knowledge base.

    update_failure is why pulling the knowledge base just failed, or None if it succeeded.
    """
    now = clock.now()
    marker = out_dir / LAST_UPDATED
    if update_failure is None:
        last_updated: datetime | None = now
    else:
        last_updated = datetime.fromisoformat(marker.read_text().strip()) if marker.is_file() else None
    banner = _banner(update_failure, last_updated)
    covers = Path(os.path.relpath((kb_dir / "entries").resolve(), out_dir.resolve())).as_posix()
    top, nested = _Links("", covers), _Links("../", covers)
    # Shortcodes are entry file names, so a page can't land outside the site.
    entries = read_entries(kb_dir)
    pages = {
        "index.html": _page("Library", _library(kb_dir, entries, top), banner, top, script=LIBRARY_JS),
        "status.html": _page("Status", _status(kb_dir, cycle_runs, now), banner, top),
    }
    for entry in entries:
        pages[f"entry/{entry.shortcode}.html"] = _page(entry.listing.problem, _entry_page(kb_dir, entry, nested), banner, nested, script=ENTRY_JS)
    (out_dir / "entry").mkdir(parents=True, exist_ok=True)
    for name, html in pages.items():
        (out_dir / name).write_text(html)
    # Pages of entries that have since been deleted from the knowledge base.
    for stale in (out_dir / "entry").glob("*.html"):
        if f"entry/{stale.name}" not in pages:
            stale.unlink()
    if update_failure is None:
        marker.write_text(now.isoformat() + "\n")


def _banner(update_failure: str | None, last_updated: datetime | None) -> str | None:
    if update_failure is None:
        return None
    since = f"since {last_updated.strftime('%Y-%m-%d %H:%M')} UTC" if last_updated else "lately"
    return f"Not updated {since}: {update_failure}. This is built from your local files."


# Library


def _library(kb_dir: Path, all_entries: list[Entry], links: _Links) -> str:
    entries = {entry.shortcode: entry for entry in all_entries}
    if not entries:
        return '<p class="empty">No entries yet. Share a reel with the bot; the next cycle adds it here.</p>'
    categories = read_categories(kb_dir)
    listings = [entry.listing for entry in entries.values()]
    ordered = [entries[listing.shortcode] for listing in pinned_then_newest(listings)]
    category_chips = "".join(
        f'<button class="chip" data-category="{escape(slug)}">{escape(category_name(slug))} <span class="count">{len(members)}</span></button>'
        for slug, members in by_category(listings, categories).items()
    )
    tools = Counter(tool for entry in ordered for tool in entry.tools)
    tags = Counter(tag for entry in ordered for tag in entry.tags)
    payload = [_searchable(entry, filed_under(entry.listing, categories)) for entry in ordered]
    cards = "".join(_card(kb_dir, entry, filed_under(entry.listing, categories), links) for entry in ordered)
    return f"""
<div class="library">
  <aside class="filters">
    <input id="search" type="search" placeholder="Search problems, approaches, steps, creators…" autofocus>
    <h3>Category</h3><div class="chips">{category_chips}</div>
    {_facet("Tools", "tool", tools)}
    {_facet("Tags", "tag", tags)}
  </aside>
  <section>
    <p id="no-match" class="empty" hidden>Nothing matches these filters. <button id="clear" class="link">Clear filters</button></p>
    <div class="grid">{cards}</div>
  </section>
</div>
<script type="application/json" id="entries">{_json(payload)}</script>"""


def _facet(title: str, kind: str, counts: Counter[str]) -> str:
    if not counts:
        return ""
    chips = "".join(
        f'<button class="chip" data-{kind}="{escape(value)}">{escape(value)} <span class="n">{count}</span></button>'
        for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
    )
    return f'<h3>{title}</h3><div class="chips">{chips}</div>'


def _searchable(entry: Entry, category: str) -> dict[str, object]:
    """What the in-page search sees: never the raw transcript or on-screen text, which are full of OCR noise."""
    sections = entry.sections()
    return {
        "shortcode": entry.shortcode,
        "problem": entry.listing.problem,
        "approach": entry.listing.approach,
        **{key: sections.get(heading, "") for key, heading in SECTIONS_SEARCHED.items()},
        "creator": entry.creator,
        "category": category,
        "tools": entry.tools,
        "tags": entry.tags,
    }


def _json(value: object) -> str:
    # Inside <script>, a "</script>" in some entry's text would end the block early.
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")


def _card(kb_dir: Path, entry: Entry, category: str, links: _Links) -> str:
    listing = entry.listing
    pin = '<span class="pin" title="Pinned">📌</span>' if listing.pinned else ""
    creator = f"@{escape(entry.creator)} · " if entry.creator else ""
    return f"""
<a class="card" data-shortcode="{listing.shortcode}" href="{links.entry(listing.shortcode)}">
  {_cover(kb_dir, entry, category, links)}
  <div class="card-body">
    <div class="card-top"><span class="cat" style="--hue: {_hue(category)}">{escape(category_name(category))}</span>{pin}</div>
    <p class="problem">{escape(listing.problem)} <span class="arrow">→</span> <span class="approach">{escape(listing.approach)}</span></p>
    <p class="meta">{creator}{escape(listing.date_added)}</p>
  </div>
</a>"""


def _cover(kb_dir: Path, entry: Entry, category: str, links: _Links) -> str:
    if cover_path(kb_dir, entry.shortcode).is_file():
        return f'<img class="cover" src="{escape(links.cover(entry.shortcode))}" alt="" loading="lazy">'
    return f'<div class="placeholder" style="--hue: {_hue(category)}"><span>{escape(category_name(category))}</span></div>'


def _hue(category: str) -> int:
    """A stable colour per category, the same on every card and every run."""
    return zlib.crc32(category.encode()) % 360


# Entry page


def _entry_page(kb_dir: Path, entry: Entry, links: _Links) -> str:
    listing = entry.listing
    category = filed_under(listing, read_categories(kb_dir))
    reel_url = entry.source_url if entry.source_url.startswith("https://") else ""
    cover = _cover(kb_dir, entry, category, links)
    if reel_url:
        cover = f'<a class="hero" href="{escape(reel_url)}" target="_blank" rel="noopener" title="Watch on Instagram">{cover}</a>'
    question = f'/ai-kb how do I apply "{listing.approach}" (entry {listing.shortcode})?'
    details = [
        ("Creator", f"@{escape(entry.creator)}" if entry.creator else "—"),
        ("Added", escape(listing.date_added)),
        ("Category", f'<span class="cat" style="--hue: {_hue(category)}">{escape(category_name(category))}</span>'),
        ("Tools", _tags(entry.tools)),
        ("Tags", _tags(entry.tags)),
    ]
    metadata = "".join(f"<dt>{name}</dt><dd>{value}</dd>" for name, value in details)
    sections = "".join(f"<section><h2>{escape(heading)}</h2>{_markdown.render(text)}</section>" for heading, text in entry.sections().items())
    watch = f'<a class="button" href="{escape(reel_url)}" target="_blank" rel="noopener">Watch the reel ↗</a>' if reel_url else ""
    return f"""
<p><a href="{links.page('index')}">← Library</a></p>
<article class="entry">
  <div class="entry-head">
    {cover}
    <div>
      {'<p class="pin">📌 Pinned</p>' if listing.pinned else ""}
      <h1>{escape(listing.problem)}</h1>
      <p class="lede">→ {escape(listing.approach)}</p>
      <dl>{metadata}</dl>
      <p class="actions"><button class="button primary" data-copy="{escape(question)}">Copy /ai-kb question</button> {watch}</p>
    </div>
  </div>
  <div class="sections">{sections}</div>
  <details>
    <summary>Raw transcript and on-screen text</summary>
    <h3>Transcript</h3><pre>{escape(entry.raw_text("Transcript")) or "(none)"}</pre>
    <h3>On-screen text</h3><pre>{escape(entry.raw_text("On-screen text")) or "(none)"}</pre>
  </details>
</article>"""


def _tags(values: list[str]) -> str:
    return " ".join(f'<span class="tag">{escape(value)}</span>' for value in values) or "—"


# Status


def _status(kb_dir: Path, cycle_runs: CycleRuns, now: datetime) -> str:
    runs = cycle_runs.latest()
    return f"""
<h1>Pipeline status</h1>
<p class="muted">Snapshot taken {now.strftime("%Y-%m-%d %H:%M")} UTC; rebuilt every hour.</p>
{_queue_state(kb_dir)}
{_runs(runs) if runs is not None else ""}"""


def _queue_state(kb_dir: Path) -> str:
    try:
        state = load_state(kb_dir)
    except (ValueError, KeyError, TypeError) as error:
        return f'<p class="error">{STATE_FILE} could not be read: {escape(str(error))}</p>'
    processed = len(state.processed)
    return f"""
<p class="stat"><strong>{processed}</strong> {"reel" if processed == 1 else "reels"} processed</p>
{_queue("Pending", "Retried by the next cycle.", state.pending)}
{_queue("Failed", "Given up on after three attempts. Share the reel again to retry it.", state.failed)}"""


def _queue(title: str, note: str, items: list[QueueItem]) -> str:
    if not items:
        return f'<section><h2>{title}</h2><p class="muted">None.</p></section>'
    rows = "".join(
        f'<tr><td><a href="{escape(item.url)}" target="_blank" rel="noopener">{escape(item.shortcode)}</a></td>'
        f'<td>{item.attempts} {"attempt" if item.attempts == 1 else "attempts"}</td>'
        f'<td class="error">{escape(item.last_error or "")}</td></tr>'
        for item in items
    )
    return f'<section><h2>{title} <span class="count">{len(items)}</span></h2><p class="muted">{note}</p><table>{rows}</table></section>'


def _runs(runs: list[CycleRun]) -> str:
    rows = "".join(
        f'<tr><td>{run.started_at.strftime("%Y-%m-%d %H:%M")} UTC</td>'
        f'<td><span class="outcome {escape(run.outcome)}">{escape(run.outcome)}</span></td>'
        f'<td><a href="{escape(run.url)}" target="_blank" rel="noopener">Logs ↗</a></td></tr>'
        for run in runs
    )
    body = f"<table>{rows}</table>" if runs else '<p class="muted">No runs yet.</p>'
    return f'<section id="runs"><h2>Recent cycles</h2>{body}</section>'


# Layout


def _page(title: str, body: str, banner: str | None, links: _Links, script: str = "") -> str:
    notice = f'<div class="banner">{escape(banner)}</div>' if banner else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · AI knowledge base</title>
<style>{CSS}</style>
</head>
<body>
<header><a class="brand" href="{links.page('index')}">AI knowledge base</a><nav><a href="{links.page('index')}">Library</a><a href="{links.page('status')}">Status</a></nav></header>
{notice}
<main>{body}</main>
<script>{script}</script>
</body>
</html>
"""


CSS = """
:root { --bg: #f6f5f2; --card: #fff; --ink: #1d1d1f; --muted: #6b6b70; --line: #e4e2dc; --accent: #3a5bd9; }
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--ink); }
a { color: var(--accent); text-decoration: none; }
header { display: flex; align-items: center; gap: 2rem; padding: .9rem 2rem; background: var(--card); border-bottom: 1px solid var(--line); }
header .brand { font-weight: 700; color: var(--ink); }
header nav a { margin-right: 1.2rem; color: var(--muted); }
main { max-width: 1280px; margin: 0 auto; padding: 1.5rem 2rem 4rem; }
.banner { background: #fff4d6; border-bottom: 1px solid #f0d58a; padding: .6rem 2rem; }
.empty { color: var(--muted); font-size: 1.05rem; padding: 3rem 0; text-align: center; }
.muted { color: var(--muted); }
.library { display: grid; grid-template-columns: 260px 1fr; gap: 2rem; align-items: start; }
.filters { position: sticky; top: 1rem; }
.filters h3 { font-size: .75rem; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin: 1.2rem 0 .4rem; }
#search { width: 100%; padding: .55rem .8rem; border: 1px solid var(--line); border-radius: 8px; font: inherit; }
.chips { display: flex; flex-wrap: wrap; gap: .35rem; }
.chip { border: 1px solid var(--line); background: var(--card); border-radius: 999px; padding: .2rem .7rem; font: inherit; font-size: .85rem; cursor: pointer; }
.chip[aria-pressed="true"] { background: var(--ink); color: #fff; border-color: var(--ink); }
.chip .count, .chip .n { color: var(--muted); font-size: .75rem; }
.chip[aria-pressed="true"] .count, .chip[aria-pressed="true"] .n { color: #ccc; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 1.2rem; }
.card { display: flex; flex-direction: column; background: var(--card); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; color: inherit; transition: transform .12s, box-shadow .12s; }
.card[hidden] { display: none; }
.card:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,.08); }
.cover, .placeholder { width: 100%; aspect-ratio: 4 / 5; object-fit: cover; display: block; }
.placeholder { display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, hsl(var(--hue) 45% 88%), hsl(var(--hue) 40% 72%)); color: hsl(var(--hue) 35% 30%); font-weight: 600; }
.card-body { padding: .8rem .9rem 1rem; }
.card-top { display: flex; justify-content: space-between; align-items: center; }
.cat { display: inline-block; font-size: .75rem; font-weight: 600; padding: .1rem .55rem; border-radius: 999px; background: hsl(var(--hue) 55% 92%); color: hsl(var(--hue) 45% 30%); }
.problem { margin: .5rem 0 .4rem; font-weight: 600; line-height: 1.35; }
.problem .arrow { color: var(--muted); }
.problem .approach { font-weight: 400; }
.meta { margin: 0; color: var(--muted); font-size: .85rem; }
.entry { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 2rem; }
.entry-head { display: grid; grid-template-columns: 320px 1fr; gap: 2rem; margin-bottom: 1.5rem; }
.entry-head .hero, .entry-head > .placeholder, .entry-head > .cover { border-radius: 10px; overflow: hidden; display: block; }
.entry h1 { margin: 0 0 .3rem; font-size: 1.6rem; line-height: 1.25; }
.lede { font-size: 1.15rem; color: #333; margin: 0 0 1rem; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: .3rem 1rem; margin: 0 0 1.2rem; }
dt { color: var(--muted); }
dd { margin: 0; }
.tag { display: inline-block; background: #f0efeb; border-radius: 6px; padding: 0 .45rem; font-size: .85rem; margin: 0 .2rem .2rem 0; }
.button { display: inline-block; border: 1px solid var(--line); background: var(--card); border-radius: 8px; padding: .45rem .9rem; font: inherit; cursor: pointer; color: var(--ink); }
.button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.link { border: 0; background: none; color: var(--accent); font: inherit; cursor: pointer; padding: 0; }
.sections { max-width: 760px; }
.sections h2 { font-size: 1.1rem; margin: 1.6rem 0 .4rem; }
code { background: #f0efeb; border-radius: 4px; padding: .05rem .3rem; font-size: .9em; }
pre { background: #f6f5f2; border-radius: 8px; padding: .8rem 1rem; white-space: pre-wrap; }
pre code { background: none; padding: 0; }
details { margin-top: 2rem; border-top: 1px solid var(--line); padding-top: 1rem; }
summary { cursor: pointer; color: var(--muted); }
.stat { font-size: 1.1rem; }
.stat strong { font-size: 2rem; }
table { border-collapse: collapse; width: 100%; background: var(--card); border: 1px solid var(--line); border-radius: 10px; }
td { padding: .5rem .8rem; border-top: 1px solid var(--line); vertical-align: top; }
td.error { font-family: ui-monospace, monospace; font-size: .85rem; }
.outcome { font-weight: 600; }
.outcome.success { color: #1d7a3a; }
.outcome.failure, .outcome.cancelled, .outcome.timed_out { color: #b3261e; }
@media (max-width: 800px) { .library, .entry-head { grid-template-columns: 1fr; } .filters { position: static; } }
"""

LIBRARY_JS = """
const entries = JSON.parse(document.getElementById("entries").textContent);
const byCode = new Map(entries.map(e => [e.shortcode, e]));
const text = new Map(entries.map(e => [e.shortcode,
  [e.problem, e.approach, e.summary, e.technique, e.steps, e.creator].join(" ").toLowerCase()]));
const search = document.getElementById("search");
const selected = { category: new Set(), tool: new Set(), tag: new Set() };

function matches(e, words) {
  return (!selected.category.size || selected.category.has(e.category))
    && [...selected.tool].every(t => e.tools.includes(t))
    && [...selected.tag].every(t => e.tags.includes(t))
    && words.every(w => text.get(e.shortcode).includes(w));
}

function apply() {
  const words = search.value.toLowerCase().split(/\\s+/).filter(Boolean);
  let shown = 0;
  for (const card of document.querySelectorAll(".card")) {
    card.hidden = !matches(byCode.get(card.dataset.shortcode), words);
    if (!card.hidden) shown++;
  }
  document.getElementById("no-match").hidden = shown > 0;
}

for (const chip of document.querySelectorAll(".filters .chip")) {
  const kind = ["category", "tool", "tag"].find(k => chip.dataset[k] !== undefined);
  chip.addEventListener("click", () => {
    const value = chip.dataset[kind];
    if (kind === "category") {
      // One category at a time: picking another switches to it.
      const was = selected.category.has(value);
      selected.category.clear();
      document.querySelectorAll(".chip[data-category]").forEach(c => c.setAttribute("aria-pressed", "false"));
      if (!was) selected.category.add(value);
    } else if (selected[kind].has(value)) selected[kind].delete(value);
    else selected[kind].add(value);
    chip.setAttribute("aria-pressed", String(selected[kind].has(value)));
    apply();
  });
}

search.addEventListener("input", apply);
document.getElementById("clear").addEventListener("click", () => {
  Object.values(selected).forEach(s => s.clear());
  document.querySelectorAll(".filters .chip").forEach(c => c.setAttribute("aria-pressed", "false"));
  search.value = "";
  apply();
});
"""

ENTRY_JS = """
for (const button of document.querySelectorAll("[data-copy]")) {
  button.addEventListener("click", async () => {
    await navigator.clipboard.writeText(button.dataset.copy);
    const label = button.textContent;
    button.textContent = "Copied";
    setTimeout(() => { button.textContent = label; }, 1500);
  });
}
"""
