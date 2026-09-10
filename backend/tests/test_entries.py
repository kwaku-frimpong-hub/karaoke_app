"""Tests for the song preview endpoint (M6).

Covers participant auth, session binding, ended-session guard, URL validation,
metadata return, and the long-video warning. The YouTube fetch itself is
mocked; the real Data API parsing is covered in test_youtube.py.
"""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.schemas.youtube import YouTubeVideoData
from app.services.youtube import (
    YouTubeQuotaExceededError,
    YouTubeServiceConfigurationError,
    YouTubeVideoUnavailableError,
    youtube_service,
)

PREVIEW_URL = "/api/v1/sessions/{session_id}/entries/preview"
REGISTER_URL = "/api/v1/auth/host/register"
LOGIN_URL = "/api/v1/auth/host/login"
SESSIONS_URL = "/api/v1/sessions"
JOIN_URL = "/api/v1/join"

EMAIL = "host@example.com"
OTHER_EMAIL = "other@example.com"
PASSWORD = "correct-horse-battery-staple"

VIDEO_ID = "dQw4w9WgXcQ"
WATCH_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


def _create_session_with_participant(
    client: TestClient, email: str = EMAIL
) -> tuple[str, str, dict]:
    """Return (participant_token, session_id, session_body)."""
    register = client.post(REGISTER_URL, json={"email": email, "password": PASSWORD})
    assert register.status_code == 201, register.text
    login = client.post(LOGIN_URL, json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    created = client.post(SESSIONS_URL, json={}, headers=headers)
    assert created.status_code == 201, created.text
    session_body = created.json()

    joined = client.post(
        f"{JOIN_URL}/{session_body['join_code']}/participants",
        json={"nickname": "Alice"},
    )
    assert joined.status_code == 201, joined.text
    return joined.json()["token"], session_body["id"], session_body


def _preview(
    client: TestClient, session_id: str, token: str, youtube_url: str = WATCH_URL
) -> httpx.Response:
    return client.post(
        PREVIEW_URL.format(session_id=session_id),
        json={"youtube_url": youtube_url},
        headers={"Authorization": f"Bearer {token}"},
    )


def _sample_metadata(duration_seconds: int = 213) -> YouTubeVideoData:
    return YouTubeVideoData(
        video_id=VIDEO_ID,
        youtube_url=WATCH_URL,
        title="Never Gonna Give You Up",
        channel="Rick Astley",
        duration_seconds=duration_seconds,
        thumbnail_url="https://i.ytimg.com/vi/medium.jpg",
    )


# --- Auth / binding ------------------------------------------------------------


def test_preview_requires_participant_authentication(client: TestClient) -> None:
    response = client.post(
        PREVIEW_URL.format(session_id=uuid.uuid4()),
        json={"youtube_url": WATCH_URL},
    )
    assert response.status_code == 401


def test_preview_rejects_participant_from_another_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token_a, session_a_id, _ = _create_session_with_participant(client, email=EMAIL)
    _, session_b_id, _ = _create_session_with_participant(
        client, email=OTHER_EMAIL
    )

    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        return _sample_metadata()

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)
    response = _preview(client, session_b_id, token_a)  # token from session A
    assert response.status_code == 404
    assert session_a_id != session_b_id


def test_preview_unknown_session_is_not_found(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, _, _ = _create_session_with_participant(client)

    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        return _sample_metadata()

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)
    response = _preview(client, str(uuid.uuid4()), token)
    assert response.status_code == 404


def test_preview_ended_session_conflicts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, session_id, _ = _create_session_with_participant(client)
    client.post(f"{SESSIONS_URL}/{session_id}/end", headers=_owner_headers(client))

    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        return _sample_metadata()

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)
    response = _preview(client, session_id, token)
    assert response.status_code == 409
    assert "ended" in response.json()["detail"]


def _owner_headers(client: TestClient) -> dict[str, str]:
    login = client.post(LOGIN_URL, json={"email": EMAIL, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


# --- URL validation / metadata ------------------------------------------------


def test_preview_rejects_invalid_url(client: TestClient) -> None:
    token, session_id, _ = _create_session_with_participant(client)
    response = _preview(client, session_id, token, youtube_url="not-a-youtube-url")
    assert response.status_code == 422
    assert "valid YouTube link" in response.json()["detail"]


def test_preview_returns_metadata(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    token, session_id, _ = _create_session_with_participant(client)

    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        assert video_id == VIDEO_ID
        return _sample_metadata()

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)
    response = _preview(client, session_id, token, youtube_url=WATCH_URL)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["video_id"] == VIDEO_ID
    assert body["youtube_url"] == WATCH_URL
    assert body["title"] == "Never Gonna Give You Up"
    assert body["channel"] == "Rick Astley"
    assert body["duration_seconds"] == 213
    assert body["thumbnail_url"] == "https://i.ytimg.com/vi/medium.jpg"
    assert body["is_long"] is False
    assert body["warning"] is None


def test_preview_long_video_warns_but_is_not_rejected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, session_id, _ = _create_session_with_participant(client)

    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        return _sample_metadata(duration_seconds=1500)  # 25 min > 10 min default

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)
    response = _preview(client, session_id, token)
    assert response.status_code == 200
    body = response.json()
    assert body["is_long"] is True
    assert body["warning"] is not None
    assert "unusually long" in body["warning"]


def test_preview_unavailable_video_is_not_found(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, session_id, _ = _create_session_with_participant(client)

    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        raise YouTubeVideoUnavailableError(video_id)

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)
    response = _preview(client, session_id, token)
    assert response.status_code == 404
    assert "couldn't load" in response.json()["detail"]


def test_preview_quota_error_is_service_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, session_id, _ = _create_session_with_participant(client)

    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        raise YouTubeQuotaExceededError(video_id)

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)
    response = _preview(client, session_id, token)
    assert response.status_code == 503
    assert "quota" in response.json()["detail"]


def test_preview_unconfigured_service_is_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, session_id, _ = _create_session_with_participant(client)

    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        raise YouTubeServiceConfigurationError("KARAOKE_YOUTUBE_API_KEY is not configured")

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)
    response = _preview(client, session_id, token)
    assert response.status_code == 503
