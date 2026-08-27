"""Unit tests for the YouTube URL validation and metadata service (M6).

The Data API fetch is tested with an ``httpx.MockTransport`` so no network is
required. Long-video warnings are covered at the endpoint level (test_entries).
"""

import httpx
import pytest

from app.schemas.youtube import YouTubeVideoData
from app.services.youtube import (
    YouTubeService,
    YouTubeServiceConfigurationError,
    YouTubeVideoUnavailableError,
    extract_video_id,
    format_duration,
    parse_iso_duration,
)

VIDEO_ID = "dQw4w9WgXcQ"


# --- extract_video_id ---------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123&index=2",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?t=42",
        "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    ],
)
def test_extract_video_id_supported_urls(url: str) -> None:
    assert extract_video_id(url) == VIDEO_ID


@pytest.mark.parametrize(
    "url",
    [
        "",
        "not a url",
        "https://example.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch",
        "https://www.youtube.com/watch?list=PL123",
        "https://youtu.be/",
        "https://youtu.be/short",
        "https://www.youtube.com/watch?v=toolongvideoId123456",
        "youtube.com/watch?v=dQw4w9WgXcQ",  # no scheme
        "ftp://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/watch?v=",
    ],
)
def test_extract_video_id_rejects_invalid_urls(url: str) -> None:
    assert extract_video_id(url) is None


# --- parse_iso_duration / format_duration -------------------------------------


@pytest.mark.parametrize(
    ("duration", "seconds"),
    [
        ("PT4M13S", 253),
        ("PT1H2M3S", 3723),
        ("PT1M", 60),
        ("PT30S", 30),
        ("PT0S", 0),
        ("garbage", 0),
        ("", 0),
    ],
)
def test_parse_iso_duration(duration: str, seconds: int) -> None:
    assert parse_iso_duration(duration) == seconds


def test_format_duration() -> None:
    assert format_duration(253) == "4:13"
    assert format_duration(3723) == "1:02:03"
    assert format_duration(0) == "0:00"


# --- fetch_video_metadata (Data API) -------------------------------------------


def _video_api_response(video_id: str = VIDEO_ID) -> dict:
    return {
        "items": [
            {
                "id": video_id,
                "snippet": {
                    "title": "Rick Astley - Never Gonna Give You Up",
                    "channelTitle": "Rick Astley",
                    "thumbnails": {
                        "default": {"url": "https://i.ytimg.com/vi/default.jpg"},
                        "medium": {"url": "https://i.ytimg.com/vi/medium.jpg"},
                    },
                },
                "contentDetails": {"duration": "PT3M33S"},
            }
        ]
    }


def _client_for(response: dict, status_code: int = 200) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "www.googleapis.com"
        return httpx.Response(status_code, json=response)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_metadata_parses_data_api_response() -> None:
    service = YouTubeService(api_key="test-key")
    async with _client_for(_video_api_response()) as client:
        data = await service.fetch_video_metadata(VIDEO_ID, client=client)

    assert isinstance(data, YouTubeVideoData)
    assert data.video_id == VIDEO_ID
    assert data.youtube_url == f"https://www.youtube.com/watch?v={VIDEO_ID}"
    assert data.title == "Rick Astley - Never Gonna Give You Up"
    assert data.channel == "Rick Astley"
    assert data.duration_seconds == 213
    assert data.thumbnail_url == "https://i.ytimg.com/vi/medium.jpg"


async def test_fetch_metadata_missing_api_key_raises_configuration_error() -> None:
    service = YouTubeService(api_key="")
    with pytest.raises(YouTubeServiceConfigurationError):
        await service.fetch_video_metadata(VIDEO_ID)


async def test_fetch_metadata_empty_items_raises_unavailable() -> None:
    service = YouTubeService(api_key="test-key")
    async with _client_for({"items": []}) as client:
        with pytest.raises(YouTubeVideoUnavailableError):
            await service.fetch_video_metadata(VIDEO_ID, client=client)


async def test_fetch_metadata_http_error_raises_unavailable() -> None:
    service = YouTubeService(api_key="test-key")
    async with _client_for({}, status_code=403) as client:
        with pytest.raises(YouTubeVideoUnavailableError):
            await service.fetch_video_metadata(VIDEO_ID, client=client)


async def test_fetch_metadata_missing_title_raises_unavailable() -> None:
    response = _video_api_response()
    response["items"][0]["snippet"] = {}
    service = YouTubeService(api_key="test-key")
    async with _client_for(response) as client:
        with pytest.raises(YouTubeVideoUnavailableError):
            await service.fetch_video_metadata(VIDEO_ID, client=client)


async def test_fetch_metadata_transport_error_raises_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    service = YouTubeService(api_key="test-key")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(YouTubeVideoUnavailableError):
            await service.fetch_video_metadata(VIDEO_ID, client=client)


async def test_fetch_metadata_non_json_body_raises_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    service = YouTubeService(api_key="test-key")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(YouTubeVideoUnavailableError):
            await service.fetch_video_metadata(VIDEO_ID, client=client)


# --- Metadata cache (M17, quota protection) ---------------------------------------


async def test_fetch_metadata_caches_repeated_lookups() -> None:
    """The same video fetched twice costs one API call (M17)."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_video_api_response())

    service = YouTubeService(api_key="test-key")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first = await service.fetch_video_metadata(VIDEO_ID, client=client)
        second = await service.fetch_video_metadata(VIDEO_ID, client=client)

    assert first == second
    assert calls["n"] == 1


async def test_fetch_metadata_cache_clears() -> None:
    """clear_cache() forces a fresh fetch (admin/tests)."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_video_api_response())

    service = YouTubeService(api_key="test-key")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await service.fetch_video_metadata(VIDEO_ID, client=client)
        await service.fetch_video_metadata(VIDEO_ID, client=client)
        assert calls["n"] == 1

        service.clear_cache()
        await service.fetch_video_metadata(VIDEO_ID, client=client)
    assert calls["n"] == 2
