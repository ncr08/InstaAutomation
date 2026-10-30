from pathlib import Path
from typing import Any

import httpx
import pytest

from instaautomation.hikerapi import HikerReelSource, ReelSourceError
from instaautomation.ports import Reel

URL = "https://www.instagram.com/reel/DAbc123XyZ/"
VIDEO_URL = "https://scontent.cdninstagram.com/v/DAbc123XyZ.mp4"
VIDEO_BYTES = b"\x00\x00\x00\x18ftypmp42"
MEDIA = {
    "pk": "1",
    "id": "1_2",
    "code": "DAbc123XyZ",
    "media_type": 2,
    "user": {"pk": "2", "username": "aitipsdaily"},
    "caption_text": "Stop clicking approve #claudecode",
    "video_url": VIDEO_URL,
}


class FakeHiker:
    def __init__(self, media: dict[str, Any] | None = None, status: int = 200) -> None:
        self.media = media or MEDIA
        self.status = status
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if str(request.url).startswith(VIDEO_URL):
            return httpx.Response(200, content=VIDEO_BYTES)
        if self.status != 200:
            return httpx.Response(self.status, json={"detail": "Media not found or unavailable", "exc_type": "NotFoundError"})
        return httpx.Response(200, json=self.media)


class FakeFallback:
    def __init__(self, reel: Reel | None = None) -> None:
        self.reel = reel
        self.urls: list[str] = []

    def __call__(self, url: str, download_dir: Path) -> Reel:
        self.urls.append(url)
        if self.reel is None:
            raise RuntimeError("yt-dlp: login required")
        return self.reel


def source_for(hiker: FakeHiker, tmp_path: Path, fallback: FakeFallback | None = None) -> HikerReelSource:
    return HikerReelSource(
        api_key="secret-key",
        download_dir=tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(hiker.handle)),
        fallback=fallback or FakeFallback(),
    )


def test_reel_url_becomes_a_downloaded_video_with_caption_creator_and_shortcode(tmp_path: Path) -> None:
    reel = source_for(FakeHiker(), tmp_path).fetch(URL)

    assert reel == Reel(
        url=URL,
        shortcode="DAbc123XyZ",
        creator="aitipsdaily",
        caption="Stop clicking approve #claudecode",
        video_path=tmp_path / "DAbc123XyZ.mp4",
    )
    assert reel.video_path.read_bytes() == VIDEO_BYTES


def test_asks_hikerapi_media_by_url_with_the_access_key_header(tmp_path: Path) -> None:
    hiker = FakeHiker()

    source_for(hiker, tmp_path).fetch(URL)

    api_call = hiker.requests[0]
    assert api_call.url.copy_with(query=None) == "https://api.hikerapi.com/v1/media/by/url"
    assert api_call.url.params["url"] == URL
    assert api_call.headers["x-access-key"] == "secret-key"
    # The key must not leak to Instagram's CDN.
    assert "x-access-key" not in hiker.requests[1].headers


def test_falls_back_to_yt_dlp_when_hikerapi_fails(tmp_path: Path) -> None:
    fallback_reel = Reel(url=URL, shortcode="DAbc123XyZ", creator="aitipsdaily", caption="", video_path=tmp_path / "x.mp4")
    fallback = FakeFallback(fallback_reel)

    reel = source_for(FakeHiker(status=404), tmp_path, fallback).fetch(URL)

    assert reel == fallback_reel
    assert fallback.urls == [URL]


def test_a_post_without_video_is_a_failure_not_an_empty_reel(tmp_path: Path) -> None:
    photo = {**MEDIA, "media_type": 1, "video_url": None}

    with pytest.raises(ReelSourceError, match="no video"):
        source_for(FakeHiker(photo), tmp_path).fetch(URL)


def test_when_both_sources_fail_the_error_names_both_reasons(tmp_path: Path) -> None:
    with pytest.raises(ReelSourceError) as raised:
        source_for(FakeHiker(status=404), tmp_path).fetch(URL)

    message = str(raised.value)
    assert "HikerAPI" in message and "404" in message
    assert "login required" in message
    assert "secret-key" not in message
