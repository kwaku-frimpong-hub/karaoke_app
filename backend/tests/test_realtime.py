"""Tests for the M10 realtime WebSocket channel.

Covers the connection auth/binding rules (participant tokens must belong to the
session; host tokens must own it), the in-process hub fan-out, and the typed
events the REST routes broadcast after domain changes:

- ``QueueUpdated``      after submit / cancel / host remove / host edit
- ``ParticipantJoined`` after a new participant registers
- ``SessionUpdated``    after the host starts/ends the session

WebSockets are a delivery mechanism, not the source of truth (D5): these tests
assert the events are *broadcast*, while the authoritative REST state remains
covered by the existing M4/M5/M7 test modules.
"""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.services.youtube import youtube_service
from app.schemas.youtube import YouTubeVideoData

REGISTER_URL = "/api/v1/auth/host/register"
LOGIN_URL = "/api/v1/auth/host/login"
SESSIONS_URL = "/api/v1/sessions"
JOIN_URL = "/api/v1/join"
SUBMIT_URL = "/api/v1/sessions/{session_id}/entries"
WS_URL = "/api/v1/sessions/{session_id}/ws"

EMAIL = "host@example.com"
OTHER_EMAIL = "other@example.com"
PASSWORD = "correct-horse-battery-staple"

VIDEO_ID = "dQw4w9WgXcQ"
WATCH_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


def _host_headers(client: TestClient, email: str = EMAIL) -> dict[str, str]:
    """Register + login a host; return the bearer headers."""
    register = client.post(REGISTER_URL, json={"email": email, "password": PASSWORD})
    assert register.status_code == 201, register.text
    login = client.post(LOGIN_URL, json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _create_session_with_participant(
    client: TestClient, email: str = EMAIL
) -> tuple[str, dict[str, str], dict[str, str]]:
    """Return (participant_token, session_body, host_headers)."""
    headers = _host_headers(client, email=email)
    created = client.post(SESSIONS_URL, json={}, headers=headers)
    assert created.status_code == 201, created.text
    session_body = created.json()
    joined = client.post(
        f"{JOIN_URL}/{session_body['join_code']}/participants",
        json={"nickname": "Alice"},
    )
    assert joined.status_code == 201, joined.text
    return joined.json()["token"], session_body, headers


def _ws_url(session_id: str, token: str) -> str:
    return WS_URL.format(session_id=session_id) + f"?token={token}"


def _sample_metadata() -> YouTubeVideoData:
    return YouTubeVideoData(
        video_id=VIDEO_ID,
        youtube_url=WATCH_URL,
        title="Never Gonna Give You Up",
        channel="Rick Astley",
        duration_seconds=213,
        thumbnail_url="https://i.ytimg.com/vi/medium.jpg",
    )


def _submit_song(
    client: TestClient, session_id: str, token: str
) -> httpx.Response:
    return client.post(
        SUBMIT_URL.format(session_id=session_id),
        json={"youtube_url": WATCH_URL},
        headers={"Authorization": f"Bearer {token}"},
    )


# --- Connection auth / binding -------------------------------------------------


def test_ws_requires_a_token(client: TestClient) -> None:
    _, session_body, _ = _create_session_with_participant(client)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            WS_URL.format(session_id=session_body["id"])
        ) as ws:
            ws.receive_text()
    assert exc_info.value.code == 1008


def test_ws_rejects_unknown_token(client: TestClient) -> None:
    _, session_body, _ = _create_session_with_participant(client)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            _ws_url(session_body["id"], "bogus-token")
        ) as ws:
            ws.receive_text()
    assert exc_info.value.code == 1008


def test_ws_rejects_participant_from_another_session(client: TestClient) -> None:
    token_a, _, _ = _create_session_with_participant(client, email=EMAIL)
    _, session_b, _ = _create_session_with_participant(client, email=OTHER_EMAIL)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(_ws_url(session_b["id"], token_a)) as ws:
            ws.receive_text()
    assert exc_info.value.code == 1008


def test_ws_rejects_unknown_session_for_participant(client: TestClient) -> None:
    token, _, _ = _create_session_with_participant(client)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            _ws_url(str(uuid.uuid4()), token)
        ) as ws:
            ws.receive_text()
    assert exc_info.value.code == 1008


def test_ws_rejects_host_who_does_not_own_session(client: TestClient) -> None:
    _, session_body, _ = _create_session_with_participant(client, email=EMAIL)
    other_headers = _host_headers(client, email=OTHER_EMAIL)
    other_token = other_headers["Authorization"].split(" ", maxsplit=1)[1]
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            _ws_url(session_body["id"], other_token)
        ) as ws:
            ws.receive_text()
    assert exc_info.value.code == 1008


# --- QueueUpdated broadcasts ---------------------------------------------------


def test_submit_broadcasts_queue_updated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, session_body, _ = _create_session_with_participant(client)

    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        assert video_id == VIDEO_ID
        return _sample_metadata()

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)

    with client.websocket_connect(_ws_url(session_body["id"], token)) as ws:
        response = _submit_song(client, session_body["id"], token)
        assert response.status_code == 201, response.text
        event = ws.receive_json()
        assert event["type"] == "QueueUpdated"
        assert event["session_id"] == session_body["id"]
        assert event["snapshot"]["session_id"] == session_body["id"]
        assert len(event["snapshot"]["queue"]) == 1
        assert event["snapshot"]["queue"][0]["participant_name"] == "Alice"


def test_cancel_broadcasts_queue_updated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, session_body, _ = _create_session_with_participant(client)

    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        return _sample_metadata()

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)

    with client.websocket_connect(_ws_url(session_body["id"], token)) as ws:
        submitted = _submit_song(client, session_body["id"], token)
        assert submitted.status_code == 201, submitted.text
        assert ws.receive_json()["type"] == "QueueUpdated"

        entry_id = submitted.json()["entry"]["id"]
        cancelled = client.delete(
            f"/api/v1/entries/{entry_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert cancelled.status_code == 204, cancelled.text
        event = ws.receive_json()
        assert event["type"] == "QueueUpdated"
        assert event["snapshot"]["queue"] == []


def test_host_remove_broadcasts_queue_updated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, session_body, headers = _create_session_with_participant(client)

    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        return _sample_metadata()

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)
    submitted = _submit_song(client, session_body["id"], token)
    assert submitted.status_code == 201, submitted.text

    host_token = headers["Authorization"].split(" ", maxsplit=1)[1]
    with client.websocket_connect(
        _ws_url(session_body["id"], host_token)
    ) as ws:
        removed = client.delete(
            f"/api/v1/entries/{submitted.json()['entry']['id']}",
            headers=headers,
        )
        assert removed.status_code == 204, removed.text
        event = ws.receive_json()
        assert event["type"] == "QueueUpdated"
        assert event["snapshot"]["queue"] == []


def test_host_edit_broadcasts_queue_updated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, session_body, headers = _create_session_with_participant(client)

    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        return _sample_metadata()

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)
    submitted = _submit_song(client, session_body["id"], token)
    assert submitted.status_code == 201, submitted.text

    host_token = headers["Authorization"].split(" ", maxsplit=1)[1]
    with client.websocket_connect(
        _ws_url(session_body["id"], host_token)
    ) as ws:
        edited = client.patch(
            f"/api/v1/entries/{submitted.json()['entry']['id']}/video",
            json={"youtube_url": WATCH_URL},
            headers=headers,
        )
        assert edited.status_code == 200, edited.text
        event = ws.receive_json()
        assert event["type"] == "QueueUpdated"
        assert len(event["snapshot"]["queue"]) == 1


# --- ParticipantJoined / SessionUpdated ----------------------------------------


def test_register_broadcasts_participant_joined(client: TestClient) -> None:
    token, session_body, _ = _create_session_with_participant(client)
    with client.websocket_connect(_ws_url(session_body["id"], token)) as ws:
        joined = client.post(
            f"{JOIN_URL}/{session_body['join_code']}/participants",
            json={"nickname": "Bob"},
        )
        assert joined.status_code == 201, joined.text
        event = ws.receive_json()
        assert event["type"] == "ParticipantJoined"
        assert event["session_id"] == session_body["id"]
        assert event["nickname"] == "Bob"


def test_start_broadcasts_session_updated(client: TestClient) -> None:
    token, session_body, headers = _create_session_with_participant(client)
    with client.websocket_connect(_ws_url(session_body["id"], token)) as ws:
        started = client.post(
            f"{SESSIONS_URL}/{session_body['id']}/start", headers=headers
        )
        assert started.status_code == 200, started.text
        event = ws.receive_json()
        assert event["type"] == "SessionUpdated"
        assert event["session_id"] == session_body["id"]
        assert event["status"] == "ACTIVE"


def test_end_broadcasts_session_updated(client: TestClient) -> None:
    _, session_body, headers = _create_session_with_participant(client)
    host_token = headers["Authorization"].split(" ", maxsplit=1)[1]
    with client.websocket_connect(
        _ws_url(session_body["id"], host_token)
    ) as ws:
        ended = client.post(
            f"{SESSIONS_URL}/{session_body['id']}/end", headers=headers
        )
        assert ended.status_code == 200, ended.text
        event = ws.receive_json()
        assert event["type"] == "SessionUpdated"
        assert event["status"] == "ENDED"
