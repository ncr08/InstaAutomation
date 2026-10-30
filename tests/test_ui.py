"""The frontend, called in-process as a WSGI app against a copy of the sample knowledge base."""

import json
import re
import shutil
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from wsgiref.util import setup_testing_defaults

import pytest

from instaautomation.fakes import FakeCycleRuns, FakeUpdater
from instaautomation.ports import CycleRun, MessageRef
from instaautomation.state import QueueItem, State, save_state
from instaautomation.ui import make_app

SAMPLE_KB = Path(__file__).resolve().parent / "fixtures" / "sample-kb"
RUN = CycleRun(
    started_at=datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc),
    outcome="failure",
    url="https://github.com/ncr08/InstaAutomation/actions/runs/123",
)


@pytest.fixture
def kb(tmp_path: Path) -> Path:
    kb_dir = tmp_path / "kb"
    shutil.copytree(SAMPLE_KB, kb_dir)
    return kb_dir


class Client:
    def __init__(self, kb_dir: Path, updater: FakeUpdater | None = None, cycle_runs: FakeCycleRuns | None = None) -> None:
        self.app = make_app(kb_dir, updater or FakeUpdater(), cycle_runs or FakeCycleRuns([RUN]))

    def get(self, path: str) -> tuple[int, dict[str, str], bytes]:
        environ: dict[str, object] = {"PATH_INFO": path}
        setup_testing_defaults(environ)
        response: dict[str, object] = {}

        def start_response(status: str, headers: list[tuple[str, str]], exc_info: object = None) -> object:
            response["status"] = int(status.split()[0])
            response["headers"] = dict(headers)
            return None

        body = b"".join(self.app(environ, start_response))  # type: ignore[arg-type]
        return response["status"], response["headers"], body  # type: ignore[return-value]

    def page(self, path: str) -> str:
        status, headers, body = self.get(path)
        assert status == 200, f"{path} gave {status}"
        assert headers["Content-Type"].startswith("text/html")
        return body.decode()


def card_order(page: str) -> list[str]:
    return re.findall(r'<a class="card[^"]*" data-shortcode="([^"]+)"', page)


def payload(page: str) -> list[dict[str, object]]:
    match = re.search(r'<script type="application/json" id="entries">(.*?)</script>', page, re.DOTALL)
    assert match
    entries: list[dict[str, object]] = json.loads(match.group(1))
    return entries


def text_of(page: str) -> str:
    return unescape(re.sub(r"<[^>]+>", " ", page))


# Library


def test_the_library_lists_every_entry_pinned_first_then_newest(kb: Path) -> None:
    page = Client(kb).page("/")

    assert card_order(page) == ["DSd4Mcp3dD", "DSa1Perm0aA", "DSb2Perm1bB", "DSc3Ctx2cC"]


def test_a_card_shows_problem_to_approach_category_creator_date_and_pin(kb: Path) -> None:
    page = Client(kb).page("/")

    card = re.search(r'<a class="card[^"]*" data-shortcode="DSd4Mcp3dD".*?</a>', page, re.DOTALL)
    assert card
    text = " ".join(text_of(card.group(0)).split())
    assert "Claude can't see GitHub issues and pull requests → Add the GitHub MCP server with claude mcp add" in text
    assert "Agents and automation" in text
    assert "@sample_creator_four" in text
    assert "2026-10-01" in text
    assert "📌" in text
    assert 'href="/entry/DSd4Mcp3dD"' in card.group(0)


def test_category_filters_show_counts_in_the_categories_file_order(kb: Path) -> None:
    page = Client(kb).page("/")

    chips = re.findall(r'data-category="([a-z-]+)"[^>]*>[^<]*<span class="count">(\d+)</span>', page)
    assert chips == [("coding-agents", "2"), ("context-and-memory", "1"), ("agents-and-automation", "1")]


def test_an_entry_in_a_category_no_longer_listed_shows_under_other(kb: Path) -> None:
    entry = kb / "entries" / "DSc3Ctx2cC.md"
    entry.write_text(entry.read_text().replace("category: context-and-memory", "category: retired-topic"))

    page = Client(kb).page("/")

    chips = re.findall(r'data-category="([a-z-]+)"[^>]*>[^<]*<span class="count">(\d+)</span>', page)
    assert chips == [("coding-agents", "2"), ("agents-and-automation", "1"), ("other", "1")]
    [entry_data] = [item for item in payload(page) if item["shortcode"] == "DSc3Ctx2cC"]
    assert entry_data["category"] == "other"


def test_tool_and_tag_filters_list_every_tool_and_tag(kb: Path) -> None:
    page = Client(kb).page("/")

    assert 'data-tool="Claude Code"' in page
    assert 'data-tag="permissions"' in page
    assert 'data-tag="mcp"' in page


def test_the_search_payload_has_the_searchable_fields_and_facets(kb: Path) -> None:
    [entry] = [item for item in payload(Client(kb).page("/")) if item["shortcode"] == "DSa1Perm0aA"]

    assert entry["problem"] == "Claude Code keeps stopping to ask permission for harmless commands"
    assert entry["approach"] == "Allowlist safe commands under permissions.allow in settings.json"
    assert "removes most prompts" in str(entry["summary"])
    assert "permissions.allow" in str(entry["technique"])
    assert "/permissions" in str(entry["steps"])
    assert entry["creator"] == "sample_creator_one"
    assert entry["category"] == "coding-agents"
    assert entry["tools"] == ["Claude Code"]
    assert entry["tags"] == ["permissions", "settings"]


def test_the_library_never_carries_the_transcript_or_on_screen_text(kb: Path) -> None:
    page = Client(kb).page("/")

    # Words that appear only in the raw transcripts of the sample entries.
    assert "hundred times" not in page
    assert "bash ls star" not in page
    for entry in payload(page):
        assert sorted(entry) == sorted(["shortcode", "problem", "approach", "summary", "technique", "steps", "creator", "category", "tools", "tags"])


def test_text_from_an_entry_cannot_break_out_of_the_page(kb: Path) -> None:
    entry = kb / "entries" / "DSa1Perm0aA.md"
    entry.write_text(
        entry.read_text().replace(
            "problem: Claude Code keeps stopping to ask permission for harmless commands",
            "problem: '</script><script>alert(1)</script> <b>bold</b>'",
        )
    )

    page = Client(kb).page("/")

    assert "<script>alert(1)" not in page
    assert "<b>bold</b>" not in page
    [entry_data] = [item for item in payload(page) if item["shortcode"] == "DSa1Perm0aA"]
    assert entry_data["problem"] == "</script><script>alert(1)</script> <b>bold</b>"


def test_an_empty_knowledge_base_says_so_and_stays_empty(tmp_path: Path) -> None:
    page = Client(tmp_path).page("/")

    assert "No entries yet" in text_of(page)
    assert list(tmp_path.iterdir()) == []


# Covers


def test_a_cover_is_served_and_shown_on_its_card(kb: Path) -> None:
    (kb / "entries" / "DSa1Perm0aA.jpg").write_bytes(b"\xff\xd8\xff fake jpeg")
    client = Client(kb)

    status, headers, body = client.get("/cover/DSa1Perm0aA.jpg")
    page = client.page("/")

    assert (status, headers["Content-Type"], body) == (200, "image/jpeg", b"\xff\xd8\xff fake jpeg")
    card = re.search(r'data-shortcode="DSa1Perm0aA".*?</a>', page, re.DOTALL)
    assert card and 'src="/cover/DSa1Perm0aA.jpg"' in card.group(0)


def test_a_card_without_a_cover_gets_a_category_tinted_placeholder(kb: Path) -> None:
    page = Client(kb).page("/")

    card = re.search(r'data-shortcode="DSb2Perm1bB".*?</a>', page, re.DOTALL)
    assert card
    assert "<img" not in card.group(0)
    assert 'class="placeholder"' in card.group(0)
    assert Client(kb).get("/cover/DSb2Perm1bB.jpg")[0] == 404


# Entry page


def test_the_entry_page_shows_metadata_and_every_section_as_written(kb: Path) -> None:
    page = Client(kb).page("/entry/DSa1Perm0aA")
    text = text_of(page)

    for heading in ["Summary", "The technique", "Step-by-step instructions", "Prerequisites", "When this is useful", "Caveats"]:
        assert f"<h2>{heading}</h2>" in page
    assert "<code>Bash(git status)</code>" in page
    assert "<li>Restart Claude Code and check with <code>/permissions</code></li>" in page
    for detail in ["@sample_creator_one", "2026-09-12", "Coding agents", "Claude Code", "permissions", "settings"]:
        assert detail in text


def test_the_entry_page_cover_links_to_the_reel(kb: Path) -> None:
    (kb / "entries" / "DSa1Perm0aA.jpg").write_bytes(b"\xff\xd8\xff")

    page = Client(kb).page("/entry/DSa1Perm0aA")

    assert re.search(r'<a [^>]*href="https://www.instagram.com/reel/DSa1Perm0aA/"[^>]*>\s*<img[^>]*src="/cover/DSa1Perm0aA.jpg"', page)


def test_the_transcript_and_on_screen_text_are_folded_away(kb: Path) -> None:
    page = Client(kb).page("/entry/DSa1Perm0aA")

    folded = re.search(r"<details>(.*?)</details>", page, re.DOTALL)
    assert folded
    assert "Stop clicking yes a hundred times." in folded.group(1)
    assert "&quot;permissions&quot;: {&quot;allow&quot;: [&quot;Bash(git status)&quot;" in folded.group(1)


def test_the_entry_page_has_a_copy_ai_kb_question_button(kb: Path) -> None:
    page = Client(kb).page("/entry/DSa1Perm0aA")

    button = re.search(r'<button[^>]*data-copy="([^"]*)"', page)
    assert button
    assert unescape(button.group(1)) == '/ai-kb how do I apply "Allowlist safe commands under permissions.allow in settings.json" (entry DSa1Perm0aA)?'


@pytest.mark.parametrize("path", ["/entry/NoSuchEntry", "/entry/..%2Fcategories", "/entry/../index", "/cover/../state.json", "/nowhere"])
def test_unknown_pages_are_not_found(kb: Path, path: str) -> None:
    status, headers, body = Client(kb).get(path)

    assert status == 404
    assert "Not found" in body.decode()


# Status


def write_state(kb_dir: Path) -> None:
    save_state(
        kb_dir,
        State(
            offset=10,
            pending=[QueueItem("DPend1", "https://www.instagram.com/reel/DPend1/", MessageRef(1, 1), attempts=2, last_error="TimeoutError: Groq timed out")],
            failed=[QueueItem("DFail1", "https://www.instagram.com/p/DFail1/", MessageRef(1, 2), attempts=3, last_error="NotAVideo: post DFail1 has no video")],
            processed={"DSa1Perm0aA", "DSb2Perm1bB", "DSc3Ctx2cC"},
        ),
    )


def test_status_lists_pending_and_failed_reels_and_the_processed_count(kb: Path) -> None:
    write_state(kb)

    page = Client(kb).page("/status")
    text = " ".join(text_of(page).split())

    assert "DPend1" in text and "2 attempts" in text and "TimeoutError: Groq timed out" in text
    assert "DFail1" in text and "NotAVideo: post DFail1 has no video" in text
    assert 'href="https://www.instagram.com/p/DFail1/"' in page
    assert "3 reels processed" in text


def test_status_shows_the_last_cycle_runs_with_links(kb: Path) -> None:
    page = Client(kb).page("/status")

    assert 'id="runs"' in page
    assert 'href="https://github.com/ncr08/InstaAutomation/actions/runs/123"' in page
    assert "failure" in page
    assert "2026-10-30 08:00" in page


def test_the_runs_panel_is_left_out_when_gh_is_unavailable(kb: Path) -> None:
    page = Client(kb, cycle_runs=FakeCycleRuns(None)).page("/status")

    assert 'id="runs"' not in page
    assert "reels processed" in page


def test_a_failed_update_shows_a_banner_with_the_reason(kb: Path) -> None:
    client = Client(kb, updater=FakeUpdater("Not possible to fast-forward, aborting."))

    for path in ["/", "/entry/DSa1Perm0aA", "/status"]:
        assert "Not possible to fast-forward, aborting." in client.page(path)


def test_no_banner_when_the_update_succeeded(kb: Path) -> None:
    assert 'class="banner"' not in Client(kb).page("/")


def test_the_update_runs_once_at_startup(kb: Path) -> None:
    updater = FakeUpdater()
    client = Client(kb, updater=updater)

    client.page("/")
    client.page("/status")

    assert updater.calls == 1


def test_no_request_writes_to_the_knowledge_base(kb: Path) -> None:
    write_state(kb)
    (kb / "categories.yml").unlink()
    before = {path: path.read_bytes() for path in kb.rglob("*") if path.is_file()}
    client = Client(kb)

    for path in ["/", "/entry/DSa1Perm0aA", "/entry/missing", "/status", "/cover/DSa1Perm0aA.jpg"]:
        client.get(path)

    assert {path: path.read_bytes() for path in kb.rglob("*") if path.is_file()} == before


def test_an_unreadable_state_file_degrades_the_status_view_instead_of_failing(kb: Path) -> None:
    (kb / "state.json").write_text("{ half-written")

    page = Client(kb).page("/status")

    assert "could not be read" in page
    assert 'id="runs"' in page
