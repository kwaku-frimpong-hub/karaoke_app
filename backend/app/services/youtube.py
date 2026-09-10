"""YouTube URL validation and metadata fetching (M6).

- ``extract_video_id`` validates supported URL shapes (watch, youtu.be, embed,
  shorts) and returns the 11-char video ID, or ``None`` for anything else.
- Metadata is normally fetched from the **YouTube Data API v3** (decision D33),
  but submit paths can fall back to keyless YouTube oEmbed when the Data API
  quota/rate limit is exhausted (D53). oEmbed lacks duration, so degraded
  metadata uses ``duration_seconds=0`` and the host remains final authority.
- Long videos produce a warning, never a rejection (decision D34, rule B6).

The service never assumes a video is a karaoke track; the host has final
authority (D7).
"""

import re
import time
from urllib.parse import parse_qs, urlparse

import httpx

from app.core.config import get_settings
from app.schemas.youtube import YouTubeVideoData

#: YouTube Data API v3 endpoint for video snippet + contentDetails.
_DATA_API_URL = "https://www.googleapis.com/youtube/v3/videos"

#: YouTube oEmbed endpoint used as a keyless fallback when Data API quota is hit.
_OEMBED_URL = "https://www.youtube.com/oembed"

#: A video ID is exactly 11 characters of the URL-safe base64 alphabet.
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
}

_YOUTUBE_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}

#: ISO 8601 duration, e.g. "PT4M13S", "PT1H2M3S".
_DURATION_RE = re.compile(
    r"^PT(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$"
)


class YouTubeVideoUnavailableError(Exception):
    """Raised when metadata cannot be fetched for a valid video ID (E4)."""


class YouTubeQuotaExceededError(Exception):
    """Raised when YouTube refuses metadata fetches because quota/rate limits are hit."""


class YouTubeServiceConfigurationError(Exception):
    """Raised when the metadata service is not configured (no API key)."""


def extract_video_id(url: str) -> str | None:
    """Return the YouTube video ID for a supported URL, or ``None``.

    Supports ``youtube.com/watch?v=`` (plus m./music. hosts), ``youtu.be/{id}``,
    ``youtube.com/embed/{id}``, and ``youtube.com/shorts/{id}``.
    """
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = parsed.netloc.lower()

    if host in _YOUTUBE_SHORT_HOSTS:
        segments = [s for s in parsed.path.split("/") if s]
        if len(segments) != 1:
            return None
        return segments[0] if _VIDEO_ID_RE.match(segments[0]) else None

    if host in _YOUTUBE_HOSTS:
        path = parsed.path
        if path == "/watch" or path.startswith("/watch/"):
            ids = parse_qs(parsed.query).get("v", [])
            if not ids:
                return None
            video_id = ids[0]
            return video_id if _VIDEO_ID_RE.match(video_id) else None
        segments = [s for s in path.split("/") if s]
        if len(segments) == 2 and segments[0] in ("embed", "shorts"):
            video_id = segments[1]
            return video_id if _VIDEO_ID_RE.match(video_id) else None
    return None


def parse_iso_duration(duration: str) -> int:
    """Convert a YouTube ISO 8601 duration (e.g. ``PT4M13S``) to seconds."""
    match = _DURATION_RE.match(duration)
    if match is None:
        return 0
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return hours * 3600 + minutes * 60 + seconds


def format_duration(total_seconds: int) -> str:
    """Format seconds as ``m:ss`` or ``h:mm:ss`` for human-readable warnings."""
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def long_video_warning(duration_seconds: int) -> str:
    """Return the warning shown for unusually long videos (never a rejection)."""
    return (
        f"This video is unusually long ({format_duration(duration_seconds)}); "
        "it may not be a karaoke track. The host has the final say."
    )


def _pick_thumbnail(thumbnails: dict[str, dict]) -> str:
    """Pick the best available thumbnail URL (medium, then default/high)."""
    for key in ("medium", "default", "high", "standard"):
        entry = thumbnails.get(key) or {}
        url = entry.get("url")
        if url:
            return url
    return ""


def _is_quota_error(response: httpx.Response) -> bool:
    """Return whether a YouTube Data API error body is a quota/rate-limit error."""
    if response.status_code not in (403, 429):
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    if payload.get("error", {}).get("status") == "RESOURCE_EXHAUSTED":
        return True
    errors = payload.get("error", {}).get("errors", [])
    for item in errors:
        reason = item.get("reason")
        if reason in {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}:
            return True
    return False


class YouTubeService:
    """Fetches YouTube metadata via the Data API v3 (decision D33)."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = (
            api_key if api_key is not None else get_settings().youtube_api_key
        )
        #: In-process metadata cache (M17): protects the Data API daily quota
        #: from repeated previews/submissions of the same video. Keyed by video
        #: id; entries expire after ``KARAOKE_YOUTUBE_CACHE_TTL_SECONDS``.
        self._cache: dict[str, tuple[float, YouTubeVideoData]] = {}

    def clear_cache(self) -> None:
        """Drop all cached metadata (used by tests and admin tooling)."""
        self._cache.clear()

    async def fetch_video_metadata(
        self, video_id: str, client: httpx.AsyncClient | None = None
    ) -> YouTubeVideoData:
        """Fetch snippet + contentDetails for ``video_id``.

        Raises ``YouTubeServiceConfigurationError`` when no API key is
        configured, ``YouTubeQuotaExceededError`` when YouTube quota/rate limits
        are exhausted, or ``YouTubeVideoUnavailableError`` for other non-200
        responses or a video with no retrievable metadata (E4). ``client`` is
        optional and lets tests inject an ``httpx.MockTransport``.

        Results are cached in-process for ``KARAOKE_YOUTUBE_CACHE_TTL_SECONDS``
        (M17): the same video previewed/submitted repeatedly — very common for
        a popular school-night song — costs one API call instead of many.
        """
        if not self._api_key:
            raise YouTubeServiceConfigurationError(
                "KARAOKE_YOUTUBE_API_KEY is not configured"
            )
        cached = self._cache.get(video_id)
        if cached is not None:
            stored_at, data = cached
            if time.monotonic() - stored_at < get_settings().youtube_cache_ttl_seconds:
                return data
        owns_client = client is None
        http = client if client is not None else httpx.AsyncClient(timeout=10.0)
        try:
            try:
                response = await http.get(
                    _DATA_API_URL,
                    params={
                        "part": "snippet,contentDetails",
                        "id": video_id,
                        "key": self._api_key,
                    },
                )
            except httpx.HTTPError as exc:
                # Transport failures (timeout/connect/DNS) are "couldn't load"
                # (E4), not server errors.
                raise YouTubeVideoUnavailableError(video_id) from exc
        finally:
            if owns_client:
                await http.aclose()

        if response.status_code != 200:
            if _is_quota_error(response):
                raise YouTubeQuotaExceededError(video_id)
            raise YouTubeVideoUnavailableError(video_id)

        try:
            payload = response.json()
        except ValueError as exc:
            # A 200 with a non-JSON body cannot be metadata (E4).
            raise YouTubeVideoUnavailableError(video_id) from exc

        items = payload.get("items") or []
        if not items:
            raise YouTubeVideoUnavailableError(video_id)
        item = items[0]
        snippet = item.get("snippet") or {}
        content = item.get("contentDetails") or {}
        title = snippet.get("title") or ""
        if not title:
            raise YouTubeVideoUnavailableError(video_id)

        data = YouTubeVideoData(
            video_id=video_id,
            youtube_url=f"https://www.youtube.com/watch?v={video_id}",
            title=title,
            channel=snippet.get("channelTitle") or "",
            duration_seconds=parse_iso_duration(content.get("duration") or ""),
            thumbnail_url=_pick_thumbnail(snippet.get("thumbnails") or {}),
        )
        self._cache[video_id] = (time.monotonic(), data)
        return data

    async def fetch_video_metadata_with_quota_fallback(
        self, video_id: str, client: httpx.AsyncClient | None = None
    ) -> YouTubeVideoData:
        """Fetch metadata, falling back to keyless oEmbed on quota/rate limits.

        Preview/edit paths still use ``fetch_video_metadata`` because they need
        authoritative duration for the long-video warning. Submit paths use this
        method so a temporary Data API quota exhaustion does not block queueing a
        song. The fallback validates that oEmbed can see the video, but duration
        is unknown and stored as 0 until a future Data API fetch refreshes it.
        """
        try:
            if client is None:
                return await self.fetch_video_metadata(video_id)
            return await self.fetch_video_metadata(video_id, client=client)
        except YouTubeQuotaExceededError:
            if client is None:
                return await self.fetch_oembed_metadata(video_id)
            return await self.fetch_oembed_metadata(video_id, client=client)

    async def fetch_oembed_metadata(
        self, video_id: str, client: httpx.AsyncClient | None = None
    ) -> YouTubeVideoData:
        """Fetch keyless oEmbed metadata for ``video_id``.

        Raises ``YouTubeVideoUnavailableError`` when oEmbed cannot load the
        video. oEmbed does not expose duration; callers receive duration 0.
        """
        owns_client = client is None
        http = client if client is not None else httpx.AsyncClient(timeout=10.0)
        try:
            try:
                response = await http.get(
                    _OEMBED_URL,
                    params={
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "format": "json",
                    },
                )
            except httpx.HTTPError as exc:
                raise YouTubeVideoUnavailableError(video_id) from exc
        finally:
            if owns_client:
                await http.aclose()

        if response.status_code != 200:
            raise YouTubeVideoUnavailableError(video_id)
        try:
            payload = response.json()
        except ValueError as exc:
            raise YouTubeVideoUnavailableError(video_id) from exc

        title = payload.get("title") or ""
        if not title:
            raise YouTubeVideoUnavailableError(video_id)
        data = YouTubeVideoData(
            video_id=video_id,
            youtube_url=f"https://www.youtube.com/watch?v={video_id}",
            title=title,
            channel=payload.get("author_name") or "",
            duration_seconds=0,
            thumbnail_url=payload.get("thumbnail_url") or "",
        )
        return data


youtube_service = YouTubeService()
