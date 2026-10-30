"""ReelSource adapter over HikerAPI, falling back to yt-dlp when HikerAPI can't deliver."""

import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from instaautomation.ports import Reel

# Confirmed against HikerAPI's OpenAPI spec (https://api.hikerapi.com/openapi.json, v1.8.3).
HIKERAPI_BASE = "https://api.hikerapi.com"
MEDIA_BY_URL = "/v1/media/by/url"
AUTH_HEADER = "x-access-key"

Fallback = Callable[[str, Path], Reel]


class ReelSourceError(RuntimeError):
    """The reel couldn't be fetched from any source."""


class NotAVideo(ReelSourceError):
    """The link is a photo or carousel post; no source will find a video in it."""


class HikerReelSource:
    def __init__(
        self,
        api_key: str,
        download_dir: Path | None = None,
        client: httpx.Client | None = None,
        fallback: Fallback | None = None,
    ) -> None:
        self._api_key = api_key
        # Outside the repo: the workflow commits the knowledge-base directory.
        self._download_dir = download_dir or Path(tempfile.mkdtemp(prefix="reels-"))
        self._client = client or httpx.Client(timeout=60, follow_redirects=True)
        self._fallback = fallback or yt_dlp_fetch

    @classmethod
    def from_env(cls) -> "HikerReelSource":
        return cls(api_key=os.environ["HIKERAPI_KEY"])

    def fetch(self, url: str) -> Reel:
        try:
            return self._fetch_from_hikerapi(url)
        except NotAVideo:
            raise
        except Exception as hiker_error:
            try:
                return self._fallback(url, self._download_dir)
            except Exception as fallback_error:
                raise ReelSourceError(f"HikerAPI: {hiker_error}; yt-dlp: {fallback_error}") from fallback_error

    def _fetch_from_hikerapi(self, url: str) -> Reel:
        response = self._client.get(f"{HIKERAPI_BASE}{MEDIA_BY_URL}", params={"url": url}, headers={AUTH_HEADER: self._api_key})
        if response.status_code != 200:
            raise ReelSourceError(f"{response.status_code} {_error_detail(response)}")
        media = response.json()
        shortcode = media["code"]
        video_url = _video_url(media)
        if not video_url:
            raise NotAVideo(f"post {shortcode} has no video")
        video_path = self._download_dir / f"{shortcode}.mp4"
        # No auth header here: the HikerAPI key is sent per request, so it never goes to Instagram's CDN.
        with self._client.stream("GET", video_url) as video:
            video.raise_for_status()
            with video_path.open("wb") as file:
                for chunk in video.iter_bytes():
                    file.write(chunk)
        return Reel(
            url=url,
            shortcode=shortcode,
            creator=(media.get("user") or {}).get("username") or "",
            caption=media.get("caption_text") or "",
            video_path=video_path,
            cover_url=_cover_url(media),
        )


def _video_url(media: dict[str, Any]) -> str | None:
    """The reel's own video, or for a carousel post (a /p/ link) its first video."""
    candidates = [media, *(media.get("resources") or [])]
    return next((item["video_url"] for item in candidates if item.get("video_url")), None)


def _cover_url(media: dict[str, Any]) -> str | None:
    candidates = [media, *(media.get("resources") or [])]
    return next((str(item["thumbnail_url"]) for item in candidates if item.get("thumbnail_url")), None)


def _error_detail(response: httpx.Response) -> str:
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    detail = body.get("detail", body) if isinstance(body, dict) else body
    return str(detail)[:100]


def yt_dlp_fetch(url: str, download_dir: Path) -> Reel:
    """Anonymous yt-dlp, without Instagram cookies: logging in from datacenter IPs gets accounts flagged."""
    import yt_dlp

    options = {
        "outtmpl": str(download_dir / "%(id)s.%(ext)s"),
        "format": "best[ext=mp4]/best",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)
        video_path = Path(downloader.prepare_filename(info))
    return Reel(
        url=url,
        shortcode=info["id"],
        creator=info.get("channel") or info.get("uploader") or "",
        caption=info.get("description") or "",
        video_path=video_path,
        cover_url=info.get("thumbnail") or None,
    )
