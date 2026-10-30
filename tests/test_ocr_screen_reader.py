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
