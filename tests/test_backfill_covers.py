from pathlib import Path

from instaautomation.entry import render_entry
from instaautomation.fakes import FakeCoverMaker, FakeReelSource
from instaautomation.pipeline import CoverReport, backfill_covers
from instaautomation.ports import EntryDraft, Reel

DRAFT = EntryDraft(
    summary="Allowlist safe commands so Claude Code stops asking.",
    problem="Claude Code keeps asking for permission on safe commands",
    approach="Allowlist read-only commands in settings.json",
    technique="Add read-only commands to the permissions allowlist in settings.json.",
    steps=["Open ~/.claude/settings.json"],
    prerequisites=[],
    when_useful="When permission prompts slow you down.",
    caveats=[],
    tools=["Claude Code"],
    tags=["permissions"],
    category="coding-agents",
)


def reel(shortcode: str) -> Reel:
    return Reel(
        url=f"https://www.instagram.com/reel/{shortcode}/",
        shortcode=shortcode,
        creator="aitipsdaily",
        caption="",
        video_path=Path(f"/videos/{shortcode}.mp4"),
    )


def write_entries(kb_dir: Path, *shortcodes: str) -> FakeReelSource:
    """Entries as an earlier cycle wrote them, and a reel source that can fetch their reels again."""
    (kb_dir / "entries").mkdir(parents=True)
    for shortcode in shortcodes:
        (kb_dir / "entries" / f"{shortcode}.md").write_text(render_entry(reel(shortcode), DRAFT, "2026-10-01", "", ""))
    return FakeReelSource([reel(shortcode) for shortcode in shortcodes])


def test_entries_without_a_cover_get_one(tmp_path: Path) -> None:
    reel_source = write_entries(tmp_path, "DAaa111", "DBbb222")

    report = backfill_covers(reel_source, FakeCoverMaker(), tmp_path)

    assert report == CoverReport(added=["DAaa111", "DBbb222"], failed={})
    assert (tmp_path / "entries" / "DAaa111.jpg").read_bytes() == FakeCoverMaker.cover_for("DAaa111")
    assert (tmp_path / "entries" / "DBbb222.jpg").read_bytes() == FakeCoverMaker.cover_for("DBbb222")


def test_existing_covers_are_left_alone_and_their_reels_not_fetched_again(tmp_path: Path) -> None:
    reel_source = write_entries(tmp_path, "DAaa111", "DBbb222")
    (tmp_path / "entries" / "DAaa111.jpg").write_bytes(b"hand-picked cover")
    # Fetching DAaa111 again would raise: the source only knows DBbb222.
    reel_source = FakeReelSource([reel("DBbb222")])
    cover_maker = FakeCoverMaker()

    report = backfill_covers(reel_source, cover_maker, tmp_path)

    assert report == CoverReport(added=["DBbb222"], failed={})
    assert cover_maker.made == ["DBbb222"]
    assert (tmp_path / "entries" / "DAaa111.jpg").read_bytes() == b"hand-picked cover"


def test_a_failure_on_one_entry_does_not_stop_the_others(tmp_path: Path) -> None:
    reel_source = write_entries(tmp_path, "DAaa111", "DBbb222")
    reel_source.fail_next(RuntimeError("reel deleted"))

    report = backfill_covers(reel_source, FakeCoverMaker(), tmp_path)

    assert report == CoverReport(added=["DBbb222"], failed={"DAaa111": "RuntimeError: reel deleted"})
    assert not (tmp_path / "entries" / "DAaa111.jpg").exists()
    assert (tmp_path / "entries" / "DBbb222.jpg").exists()


def test_the_queue_state_is_never_touched(tmp_path: Path) -> None:
    reel_source = write_entries(tmp_path, "DAaa111")
    state_before = '{"offset": 7, "pending": [], "failed": [], "processed": ["DAaa111"]}\n'
    (tmp_path / "state.json").write_text(state_before)

    backfill_covers(reel_source, FakeCoverMaker(), tmp_path)

    assert (tmp_path / "state.json").read_text() == state_before
    assert sorted(path.name for path in tmp_path.iterdir()) == ["entries", "state.json"]
