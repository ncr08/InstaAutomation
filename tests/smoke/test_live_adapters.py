"""Manual smoke tests against the live APIs. They need real keys and cost money, so CI never runs them.

    set -a; source .env; set +a
    RUN_SMOKE=1 SMOKE_REEL_URL=https://www.instagram.com/reel/<shortcode>/ uv run pytest tests/smoke -s
"""

import os
from pathlib import Path
from typing import NoReturn

import httpx
import pytest
from PIL import Image

from instaautomation.covers import FfmpegCoverMaker
from instaautomation.hikerapi import HikerReelSource, yt_dlp_fetch
from instaautomation.ports import MessageRef
from instaautomation.telegram import TelegramInbox

pytestmark = pytest.mark.skipif(os.environ.get("RUN_SMOKE") != "1", reason="live API smoke test; set RUN_SMOKE=1")


def test_telegram_lists_pending_updates_without_confirming_them() -> None:
    # Offset 0 confirms nothing, so this never loses reels the production cycle hasn't fetched yet.
    messages = TelegramInbox.from_env().fetch_messages(0)

    print(f"{len(messages)} unconfirmed update(s):", [(m.update_id, m.text[:60]) for m in messages])


def test_telegram_reacts_and_replies_with_a_reason() -> None:
    inbox = TelegramInbox.from_env()
    owner_id = int(os.environ["TELEGRAM_OWNER_ID"])
    sent = httpx.post(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
        json={"chat_id": owner_id, "text": "InstaAutomation smoke test: expect 👍, then 👎 with a reply"},
    ).json()
    assert sent["ok"], sent.get("description")
    ref = MessageRef(chat_id=owner_id, message_id=sent["result"]["message_id"])

    inbox.react(ref, "✅")
    inbox.react(ref, "❌", "Smoke test: this is where a failure reason would appear")


def test_hikerapi_downloads_a_reel(tmp_path: Path) -> None:
    source = HikerReelSource(api_key=os.environ["HIKERAPI_KEY"], download_dir=tmp_path, fallback=_no_fallback)

    reel = source.fetch(os.environ["SMOKE_REEL_URL"])

    print(reel)
    assert reel.shortcode and reel.creator
    assert reel.video_path.stat().st_size > 10_000
    assert reel.cover_url


def test_the_cover_of_a_live_reel_is_a_small_jpeg(tmp_path: Path) -> None:
    reel = HikerReelSource(api_key=os.environ["HIKERAPI_KEY"], download_dir=tmp_path).fetch(os.environ["SMOKE_REEL_URL"])

    cover = FfmpegCoverMaker().make(reel)

    (tmp_path / "cover.jpg").write_bytes(cover)
    print(f"{len(cover) // 1000} KB, open {tmp_path / 'cover.jpg'} to look at it")
    image = Image.open(tmp_path / "cover.jpg")
    assert image.format == "JPEG" and image.width <= 480
    assert len(cover) < 150_000


def test_yt_dlp_fallback_downloads_a_reel(tmp_path: Path) -> None:
    # Instagram often refuses anonymous requests; a failure here means the fallback is unavailable, not broken code.
    reel = yt_dlp_fetch(os.environ["SMOKE_REEL_URL"], tmp_path)

    print(reel)
    assert reel.video_path.stat().st_size > 10_000
    assert reel.cover_url


def _no_fallback(url: str, download_dir: Path) -> NoReturn:
    raise AssertionError("HikerAPI failed; see the chained error")
