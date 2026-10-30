from pathlib import Path

from instaautomation.ocr import OcrScreenReader

VIDEO = Path("/videos/DAbc123XyZ.mp4")


def reader_showing(*frames: str) -> OcrScreenReader:
    """A reader whose video shows `frames` in order, as tesseract would read them."""
    paths = [Path(f"/frames/{i:05d}.png") for i in range(len(frames))]
    texts = dict(zip(paths, frames))
    return OcrScreenReader(
        sample_frames=lambda video, out_dir, every_seconds: paths,
        ocr=lambda frame: texts[frame],
    )


def test_text_held_on_screen_across_frames_appears_once() -> None:
    reader = reader_showing(
        "Stop clicking approve\n3 tips for Claude Code",
        "Stop clicking approve\n3 tips for Claude Code",
        "Stop clicklng approve.\n3 tips for Claude Code",
    )

    assert reader.read(VIDEO) == "Stop clicking approve\n3 tips for Claude Code"


def test_text_typed_out_over_several_frames_keeps_the_complete_line() -> None:
    reader = reader_showing(
        "Prompt:\nclaude --permission",
        "Prompt:\nclaude --permission-mode plan",
        "Prompt:\nclaude --permission-mode plan \"refactor auth\"",
    )

    assert reader.read(VIDEO) == "Prompt:\nclaude --permission-mode plan \"refactor auth\""


def test_frames_without_text_or_with_stray_symbols_add_nothing() -> None:
    reader = reader_showing("", "\n  \n", "| ~\n—\ni", "Use /init first")

    assert reader.read(VIDEO) == "Use /init first"


def test_a_video_with_no_text_on_screen_reads_as_empty() -> None:
    assert reader_showing("", "").read(VIDEO) == ""


def test_a_short_line_is_not_lost_inside_a_longer_word() -> None:
    reader = reader_showing("Verify each claim", "AI")

    assert reader.read(VIDEO) == "Verify each claim\nAI"


def test_list_items_that_share_a_prefix_are_all_kept() -> None:
    reader = reader_showing("Step 1: open settings\nStep 12: restart")

    assert reader.read(VIDEO) == "Step 1: open settings\nStep 12: restart"


def test_a_heading_shown_on_its_own_is_kept_after_a_longer_line_containing_it() -> None:
    reader = reader_showing("3 tips for Claude Code", "Claude Code")

    assert reader.read(VIDEO) == "3 tips for Claude Code\nClaude Code"


def test_a_short_item_on_screen_alongside_a_longer_one_is_not_mistaken_for_typing() -> None:
    reader = reader_showing("Step 1", "Step 1\nStep 12")

    assert reader.read(VIDEO) == "Step 1\nStep 12"
