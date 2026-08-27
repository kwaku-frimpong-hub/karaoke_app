"""Tests for the M16 round lifecycle cleanup + summaries.

Covers absent-participant cleanup (stale participants' remaining WAITING songs
are cancelled after the cleanup window; the realtime connect refreshes
``last_connected_at``), the snapshot's round/participant summaries, and the
host-facing session summary endpoint.
"""

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.queue_entry import QueueEntryStatus
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


def _video(video_id: str) -> YouTubeVideoData:
    return YouTubeVideoData(
        video_id=video_id,
        youtube_url=f"https://www.youtube.com/watch?v={video_id}",
        title="Song",
        channel="Artist",
        duration_seconds=213,
        thumbnail_url=f"https://i.ytimg.com/vi/{video_id}/medium.jpg",
    )


def _patch_youtube(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        return _video(video_id)

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)


def _register(client: TestClient, email: str = EMAIL) -> dict[str, str]:
    register = client.post(REGISTER_URL, json={"email": email, "password": PASSWORD})
    assert register.status_code == 201, register.text
    login = client.post(LOGIN_URL, json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _setup(client: TestClient) -> tuple[dict[str, str], dict, str]:
    headers = _register(client)
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


def _submit(client: TestClient, session_id: str, token: str) -> httpx.Response:
    return client.post(
        f"{SESSIONS_URL}/{session_id}/entries",
        json={"youtube_url": f"https://youtu.be/{VIDEO_A_ID}"},
        headers={"Authorization": f"Bearer {token}"},
    )


def _snapshot(client: TestClient, session_id: str) -> dict:
    return client.get(f"{SESSIONS_URL}/{session_id}/entries").json()


async def _set_last_connected(
    session: AsyncSession, session_id: str, nickname: str, age: timedelta
) -> None:
    participant = await session.scalar(
        select(Participant).where(
            Participant.session_id == uuid.UUID(session_id),
            Participant.nickname == nickname,
        )
    )
    assert participant is not None
    participant.last_connected_at = datetime.now(timezone.utc) - age
    await session.commit()


# --- Absent-participant cleanup (M16) ---------------------------------------------


async def test_absent_participant_entries_are_cleaned(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, session: AsyncSession
) -> None:
    _patch_youtube(monkeypatch)
    headers, session_body, alice = _setup(client)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice)
    _submit(client, session_body["id"], alice)
    _submit(client, session_body["id"], bob)

    # Alice hasn't connected for hours -> her remaining songs are cleaned up.
    await _set_last_connected(
        session, session_body["id"], "Alice", timedelta(hours=2)
    )
    # Cleanup only runs for a started (ACTIVE/PAUSED) session.
    assert (
        client.post(
            f"{SESSIONS_URL}/{session_body['id']}/start", headers=headers
        ).status_code
        == 200
    )

    body = _snapshot(client, session_body["id"])
    assert [e["participant_name"] for e in body["queue"]] == ["Bob"]
    # The summary reflects only Bob's remaining songs.
    assert body["participants"] == [{"nickname": "Bob", "remaining_songs": 1}]

    stored = (
        await session.scalars(
            select(QueueEntry).where(QueueEntry.session_id == uuid.UUID(session_body["id"]))
        )
    ).all()
    alice_entries = [e for e in stored if e.participant.nickname == "Alice"]
    assert len(alice_entries) == 2
    assert all(e.status is QueueEntryStatus.CANCELLED for e in alice_entries)


def test_recently_connected_participant_is_not_cleaned(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch)
    headers, session_body, alice = _setup(client)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice)
    _submit(client, session_body["id"], bob)

    body = _snapshot(client, session_body["id"])
    assert {e["participant_name"] for e in body["queue"]} == {"Alice", "Bob"}


async def test_cleanup_does_not_run_for_created_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, session: AsyncSession
) -> None:
    _patch_youtube(monkeypatch)
    headers, session_body, alice = _setup(client)
    _submit(client, session_body["id"], alice)
    await _set_last_connected(
        session, session_body["id"], "Alice", timedelta(hours=2)
    )

    # The session is CREATED (never started): cleanup is skipped.
    body = _snapshot(client, session_body["id"])
    assert [e["participant_name"] for e in body["queue"]] == ["Alice"]


async def test_ws_connect_refreshes_last_connected_at(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, session: AsyncSession
) -> None:
    _patch_youtube(monkeypatch)
    headers, session_body, alice = _setup(client)
    await _set_last_connected(
        session, session_body["id"], "Alice", timedelta(hours=2)
    )

    before = datetime.now(timezone.utc)
    # Connecting establishes the socket; the server refreshes last_connected_at.
    with client.websocket_connect(
        WS_URL.format(session_id=session_body["id"]) + f"?token={alice}"
    ):
        pass

    participant = await session.scalar(
        select(Participant).where(
            Participant.session_id == uuid.UUID(session_body["id"]),
            Participant.nickname == "Alice",
        )
    )
    assert participant is not None
    assert participant.last_connected_at is not None
    assert participant.last_connected_at.replace(tzinfo=timezone.utc) >= before


# --- Round summaries (M16) --------------------------------------------------------


def test_snapshot_reports_rounds_completed_and_participants(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch)
    headers, session_body, alice = _setup(client)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice)
    _submit(client, session_body["id"], bob)
    _submit(client, session_body["id"], alice)  # Alice's round-2 song

    body = _snapshot(client, session_body["id"])
    assert body["round_number"] == 1
    assert body["rounds_completed"] == 0
    assert body["participants"] == [
        {"nickname": "Alice", "remaining_songs": 2},
        {"nickname": "Bob", "remaining_songs": 1},
    ]

    # Exhaust round 1 via host removals -> round 2 becomes active.
    for entry in body["queue"]:
        assert client.delete(
            f"{ENTRIES_URL}/{entry['id']}", headers=headers
        ).status_code == 204

    body = _snapshot(client, session_body["id"])
    assert body["round_number"] == 2
    assert body["rounds_completed"] == 1
    assert body["participants"] == [{"nickname": "Alice", "remaining_songs": 1}]


def test_session_summary_endpoint(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch)
    headers, session_body, alice = _setup(client)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice)
    _submit(client, session_body["id"], alice)
    _submit(client, session_body["id"], bob)

    response = client.get(
        f"{SESSIONS_URL}/{session_body['id']}/summary", headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["session_id"] == session_body["id"]
    assert body["status"] == "CREATED"
    assert body["active_round"] == 1
    assert body["rounds_completed"] == 0
    assert body["participants"] == [
        {"nickname": "Alice", "songs_submitted": 2, "songs_sung": 0, "songs_remaining": 2},
        {"nickname": "Bob", "songs_submitted": 1, "songs_sung": 0, "songs_remaining": 1},
    ]

    # After Alice sings one song, the summary reflects it.
    client.post(f"{SESSIONS_URL}/{session_body['id']}/play/start", headers=headers)
    client.post(f"{SESSIONS_URL}/{session_body['id']}/play/finish", headers=headers)
    body = client.get(
        f"{SESSIONS_URL}/{session_body['id']}/summary", headers=headers
    ).json()
    alice_stats = next(p for p in body["participants"] if p["nickname"] == "Alice")
    assert alice_stats["songs_sung"] == 1
    assert alice_stats["songs_remaining"] == 1


def test_session_summary_requires_owning_host(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch)
    _, session_body, alice = _setup(client)
    # No auth -> 401; participant token -> 401; another host -> 404.
    assert client.get(f"{SESSIONS_URL}/{session_body['id']}/summary").status_code == 401
    assert (
        client.get(
            f"{SESSIONS_URL}/{session_body['id']}/summary",
            headers={"Authorization": f"Bearer {alice}"},
        ).status_code
        == 401
    )
    other = _register(client, email=OTHER_EMAIL)
    assert (
        client.get(
            f"{SESSIONS_URL}/{session_body['id']}/summary", headers=other
        ).status_code
        == 404
    )
