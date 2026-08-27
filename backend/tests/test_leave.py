"""Tests for the participant "leave session" feature (delete self + songs).

Leaving deletes the participant row (cascading to all their queue entries and
any reorder rows), frees their nickname, kills their token, and — if they were
the current singer — advances playback (E6).
"""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.participant import Participant
from app.models.queue_entry import QueueEntry
from app.schemas.youtube import YouTubeVideoData
from app.services.youtube import (
    YouTubeVideoUnavailableError,
    youtube_service,
)

SESSIONS_URL = "/api/v1/sessions"
JOIN_URL = "/api/v1/join"
ENTRIES_URL = "/api/v1/entries"
REGISTER_URL = "/api/v1/auth/host/register"
LOGIN_URL = "/api/v1/auth/host/login"
WS_URL = "/api/v1/sessions/{session_id}/ws"

EMAIL = "host@example.com"
OTHER_EMAIL = "other@example.com"
PASSWORD = "correct-horse-battery-staple"
VIDEO_A_ID = "dQw4w9WgXcQ"


def _patch_youtube(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        return YouTubeVideoData(
            video_id=video_id,
            youtube_url=f"https://www.youtube.com/watch?v={video_id}",
            title="Song",
            channel="Artist",
            duration_seconds=213,
            thumbnail_url="",
        )

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)


def _register(client: TestClient, email: str = EMAIL) -> dict[str, str]:
    register = client.post(REGISTER_URL, json={"email": email, "password": PASSWORD})
    assert register.status_code == 201, register.text
    login = client.post(LOGIN_URL, json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _setup(
    client: TestClient, email: str = EMAIL
) -> tuple[dict[str, str], dict, str]:
    """Return (host_headers, session_body, participant_token) with one Alice."""
    headers = _register(client, email=email)
    created = client.post(SESSIONS_URL, json={}, headers=headers)
    assert created.status_code == 201, created.text
    session_body = created.json()
    joined = client.post(
        f"{JOIN_URL}/{session_body['join_code']}/participants",
        json={"nickname": "Alice"},
    )
    assert joined.status_code == 201, joined.text
    return headers, session_body, joined.json()["token"]


def _join(client: TestClient, session_body: dict, nickname: str) -> str:
    joined = client.post(
        f"{JOIN_URL}/{session_body['join_code']}/participants",
        json={"nickname": nickname},
    )
    assert joined.status_code == 201, joined.text
    return joined.json()["token"]


def _submit(
    client: TestClient, session_id: str, token: str, video_id: str = VIDEO_A_ID
) -> httpx.Response:
    return client.post(
        f"{SESSIONS_URL}/{session_id}/entries",
        json={"youtube_url": f"https://youtu.be/{video_id}"},
        headers={"Authorization": f"Bearer {token}"},
    )


def _snapshot(client: TestClient, session_id: str) -> dict:
    return client.get(f"{SESSIONS_URL}/{session_id}/entries").json()


# --- Authorization / binding --------------------------------------------------------


def test_leave_requires_participant_authentication(client: TestClient) -> None:
    assert (
        client.post(f"{SESSIONS_URL}/{uuid.uuid4()}/leave").status_code == 401
    )


def test_leave_cross_session_token_is_not_found(client: TestClient) -> None:
    _, session_body, token = _setup(client)
    _, other_session, _ = _setup(client, email=OTHER_EMAIL)
    response = client.post(
        f"{SESSIONS_URL}/{other_session['id']}/leave",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


# --- Deletion behavior ----------------------------------------------------------------


async def test_leave_deletes_participant_and_all_entries(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, session: AsyncSession
) -> None:
    _patch_youtube(monkeypatch)
    headers, session_body, alice = _setup(client)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice)
    _submit(client, session_body["id"], alice, video_id="9bZkp7q19f0")
    _submit(client, session_body["id"], bob)

    response = client.post(
        f"{SESSIONS_URL}/{session_body['id']}/leave",
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert response.status_code == 204, response.text

    # The participant row and all their entries are gone (cascade).
    assert (
        await session.scalar(
            select(func.count(Participant.id)).where(
                Participant.nickname == "Alice"
            )
        )
    ) == 0
    # Only Bob's entry remains in the session.
    total_entries = await session.scalar(
        select(func.count(QueueEntry.id)).where(
            QueueEntry.session_id == uuid.UUID(session_body["id"])
        )
    )
    assert total_entries == 1
    # Bob's song remains.
    body = _snapshot(client, session_body["id"])
    assert [e["participant_name"] for e in body["queue"]] == ["Bob"]


async def test_leave_is_absent_from_future_rounds(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, session: AsyncSession
) -> None:
    _patch_youtube(monkeypatch)
    headers, session_body, alice = _setup(client)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice)
    _submit(client, session_body["id"], bob)
    _submit(client, session_body["id"], alice, video_id="9bZkp7q19f0")  # round 2

    client.post(
        f"{SESSIONS_URL}/{session_body['id']}/leave",
        headers={"Authorization": f"Bearer {alice}"},
    )
    # Exhaust round 1 (Bob's entry) -> round 2 must NOT exist for Alice.
    body = _snapshot(client, session_body["id"])
    assert body["rounds_completed"] == 0  # round 1 still active with Bob
    # Alice's round-2 entry was cascaded away entirely.
    total_entries = await session.scalar(
        select(func.count(QueueEntry.id)).where(
            QueueEntry.session_id == uuid.UUID(session_body["id"])
        )
    )
    assert total_entries == 1  # only Bob's


def test_leave_mid_song_advances_playback(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch)
    headers, session_body, alice = _setup(client)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice)
    _submit(client, session_body["id"], bob)
    client.post(f"{SESSIONS_URL}/{session_body['id']}/play/start", headers=headers)

    response = client.post(
        f"{SESSIONS_URL}/{session_body['id']}/leave",
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert response.status_code == 204, response.text

    # Alice's singing entry is gone; Bob is promoted and the countdown begins.
    body = _snapshot(client, session_body["id"])
    assert [e["participant_name"] for e in body["queue"]] == ["Bob"]
    assert body["queue"][0]["status"] == "NEXT"
    assert body["playback_state"] == "COUNTDOWN"


def test_token_is_dead_after_leaving(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch)
    headers, session_body, alice = _setup(client)
    client.post(
        f"{SESSIONS_URL}/{session_body['id']}/leave",
        headers={"Authorization": f"Bearer {alice}"},
    )

    # The token no longer resolves: preview / submit / mine / leave all 401.
    preview = client.post(
        f"{SESSIONS_URL}/{session_body['id']}/entries/preview",
        json={"youtube_url": f"https://youtu.be/{VIDEO_A_ID}"},
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert preview.status_code == 401
    submit = client.post(
        f"{SESSIONS_URL}/{session_body['id']}/entries",
        json={"youtube_url": f"https://youtu.be/{VIDEO_A_ID}"},
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert submit.status_code == 401
    mine = client.get(
        f"{SESSIONS_URL}/{session_body['id']}/entries/mine",
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert mine.status_code == 401
    leave_again = client.post(
        f"{SESSIONS_URL}/{session_body['id']}/leave",
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert leave_again.status_code == 401


def test_nickname_is_reusable_after_leaving(client: TestClient) -> None:
    headers, session_body, alice = _setup(client)
    client.post(
        f"{SESSIONS_URL}/{session_body['id']}/leave",
        headers={"Authorization": f"Bearer {alice}"},
    )

    # The same nickname can join again as a fresh identity.
    rejoined = client.post(
        f"{JOIN_URL}/{session_body['join_code']}/participants",
        json={"nickname": "Alice"},
    )
    assert rejoined.status_code == 201
    assert rejoined.json()["participant"]["id"] != alice


def test_leave_broadcasts_queue_updated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch)
    headers, session_body, alice = _setup(client)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice)
    _submit(client, session_body["id"], bob)

    with client.websocket_connect(
        WS_URL.format(session_id=session_body["id"]) + f"?token={bob}"
    ) as ws:
        response = client.post(
            f"{SESSIONS_URL}/{session_body['id']}/leave",
            headers={"Authorization": f"Bearer {alice}"},
        )
        assert response.status_code == 204, response.text
        event = ws.receive_json()
        assert event["type"] == "QueueUpdated"
        assert [e["participant_name"] for e in event["snapshot"]["queue"]] == [
            "Bob"
        ]
