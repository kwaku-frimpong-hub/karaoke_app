"""Tests for host-assisted participant and playlist management."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.queue_entry import QueueEntryStatus
from app.models.participant import Participant
from app.models.queue_entry import QueueEntry
from app.schemas.youtube import YouTubeVideoData
from app.services.youtube import YouTubeQuotaExceededError, youtube_service

REGISTER_URL = "/api/v1/auth/host/register"
LOGIN_URL = "/api/v1/auth/host/login"
SESSIONS_URL = "/api/v1/sessions"
JOIN_URL = "/api/v1/join"
PARTICIPANTS_URL = "/api/v1/sessions/{session_id}/participants"
PARTICIPANT_ENTRIES_URL = "/api/v1/sessions/{session_id}/participants/{participant_id}/entries"
QUEUE_URL = "/api/v1/sessions/{session_id}/entries"
WS_URL = "/api/v1/sessions/{session_id}/ws"

EMAIL = "host@example.com"
OTHER_EMAIL = "other@example.com"
PASSWORD = "correct-horse-battery-staple"

VIDEO_ID = "dQw4w9WgXcQ"
WATCH_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


def _host_headers(client: TestClient, email: str = EMAIL) -> dict[str, str]:
    register = client.post(REGISTER_URL, json={"email": email, "password": PASSWORD})
    assert register.status_code == 201, register.text
    login = client.post(LOGIN_URL, json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _create_session(client: TestClient, email: str = EMAIL) -> tuple[dict, dict[str, str]]:
    headers = _host_headers(client, email=email)
    created = client.post(SESSIONS_URL, json={}, headers=headers)
    assert created.status_code == 201, created.text
    return created.json(), headers


def _create_host_participant(
    client: TestClient,
    session_id: str,
    headers: dict[str, str],
    nickname: str = "No Phone Nina",
) -> dict:
    response = client.post(
        PARTICIPANTS_URL.format(session_id=session_id),
        json={"nickname": nickname},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _sample_metadata(video_id: str = VIDEO_ID, title: str = "Never Gonna Give You Up") -> YouTubeVideoData:
    return YouTubeVideoData(
        video_id=video_id,
        youtube_url=f"https://www.youtube.com/watch?v={video_id}",
        title=title,
        channel="Rick Astley",
        duration_seconds=213,
        thumbnail_url="https://i.ytimg.com/vi/medium.jpg",
    )


def test_host_can_create_and_list_participants(client: TestClient) -> None:
    session_body, headers = _create_session(client)
    participant = _create_host_participant(client, session_body["id"], headers)

    response = client.get(
        PARTICIPANTS_URL.format(session_id=session_body["id"]), headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == [
        {
            "id": participant["id"],
            "session_id": session_body["id"],
            "nickname": "No Phone Nina",
            "created_at": participant["created_at"],
            "entries": [],
        }
    ]


async def test_host_created_participants_are_not_absence_tracked(
    client: TestClient, session: AsyncSession
) -> None:
    session_body, headers = _create_session(client)
    participant = _create_host_participant(client, session_body["id"], headers)

    stored = await session.scalar(
        select(Participant).where(Participant.id == uuid.UUID(participant["id"]))
    )
    assert stored is not None
    assert stored.last_connected_at is None


def test_host_create_rejects_taken_nickname_case_insensitive(client: TestClient) -> None:
    session_body, headers = _create_session(client)
    _create_host_participant(client, session_body["id"], headers, nickname="Sam")

    response = client.post(
        PARTICIPANTS_URL.format(session_id=session_body["id"]),
        json={"nickname": "sam"},
        headers=headers,
    )
    assert response.status_code == 409
    assert "already taken" in response.json()["detail"]


def test_host_participant_endpoints_require_host_auth(client: TestClient) -> None:
    session_body, _headers = _create_session(client)
    response = client.get(PARTICIPANTS_URL.format(session_id=session_body["id"]))
    assert response.status_code == 401

    joined = client.post(
        f"{JOIN_URL}/{session_body['join_code']}/participants",
        json={"nickname": "Alice"},
    )
    assert joined.status_code == 201, joined.text
    participant_headers = {"Authorization": f"Bearer {joined.json()['token']}"}
    response = client.post(
        PARTICIPANTS_URL.format(session_id=session_body["id"]),
        json={"nickname": "Bob"},
        headers=participant_headers,
    )
    assert response.status_code == 401


def test_host_participant_endpoints_hide_sessions_from_other_hosts(client: TestClient) -> None:
    session_body, headers = _create_session(client, email=EMAIL)
    other_headers = _host_headers(client, email=OTHER_EMAIL)

    response = client.get(
        PARTICIPANTS_URL.format(session_id=session_body["id"]), headers=other_headers
    )
    assert response.status_code == 404

    response = client.post(
        PARTICIPANTS_URL.format(session_id=session_body["id"]),
        json={"nickname": "Bob"},
        headers=other_headers,
    )
    assert response.status_code == 404
    assert headers != other_headers


def test_host_can_add_song_to_participant_playlist(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_body, headers = _create_session(client)
    participant = _create_host_participant(client, session_body["id"], headers)

    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        assert video_id == VIDEO_ID
        return _sample_metadata()

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)
    response = client.post(
        PARTICIPANT_ENTRIES_URL.format(
            session_id=session_body["id"], participant_id=participant["id"]
        ),
        json={"youtube_url": WATCH_URL},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["entry"]["participant_name"] == "No Phone Nina"
    assert body["entry"]["position"] == 1

    participants = client.get(
        PARTICIPANTS_URL.format(session_id=session_body["id"]), headers=headers
    ).json()
    assert participants[0]["entries"][0]["title"] == "Never Gonna Give You Up"
    assert participants[0]["entries"][0]["round_number"] == 1
    assert participants[0]["entries"][0]["position"] == 1

    queue = client.get(QUEUE_URL.format(session_id=session_body["id"])).json()
    assert queue["queue"][0]["participant_name"] == "No Phone Nina"


def test_host_add_queues_oembed_metadata_when_data_api_quota_is_exhausted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_body, headers = _create_session(client)
    participant = _create_host_participant(client, session_body["id"], headers)

    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        raise YouTubeQuotaExceededError(video_id)

    async def fake_oembed(video_id: str) -> YouTubeVideoData:
        return _sample_metadata(video_id=video_id, title="Fallback Host Song").model_copy(
            update={"duration_seconds": 0}
        )

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)
    monkeypatch.setattr(youtube_service, "fetch_oembed_metadata", fake_oembed)
    response = client.post(
        PARTICIPANT_ENTRIES_URL.format(
            session_id=session_body["id"], participant_id=participant["id"]
        ),
        json={"youtube_url": WATCH_URL},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    entry = response.json()["entry"]
    assert entry["title"] == "Fallback Host Song"
    assert entry["duration_seconds"] == 0


async def test_host_created_participant_song_survives_active_snapshot_cleanup(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, session: AsyncSession
) -> None:
    session_body, headers = _create_session(client)
    participant = _create_host_participant(client, session_body["id"], headers)
    started = client.post(f"{SESSIONS_URL}/{session_body['id']}/start", headers=headers)
    assert started.status_code == 200, started.text

    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        return _sample_metadata()

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)
    response = client.post(
        PARTICIPANT_ENTRIES_URL.format(
            session_id=session_body["id"], participant_id=participant["id"]
        ),
        json={"youtube_url": WATCH_URL},
        headers=headers,
    )
    assert response.status_code == 201, response.text

    queue = client.get(QUEUE_URL.format(session_id=session_body["id"])).json()
    assert queue["queue"][0]["participant_name"] == "No Phone Nina"

    entry = await session.scalar(
        select(QueueEntry).where(QueueEntry.id == uuid.UUID(response.json()["entry"]["id"]))
    )
    assert entry is not None
    assert entry.status is QueueEntryStatus.WAITING


def test_host_participant_playlist_shows_future_round_songs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_body, headers = _create_session(client)
    participant = _create_host_participant(client, session_body["id"], headers)
    seen: list[str] = []

    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        seen.append(video_id)
        return _sample_metadata(video_id=video_id, title=f"Song {len(seen)}")

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)
    for video_id in (VIDEO_ID, "M7lc1UVf-VE"):
        response = client.post(
            PARTICIPANT_ENTRIES_URL.format(
                session_id=session_body["id"], participant_id=participant["id"]
            ),
            json={"youtube_url": f"https://www.youtube.com/watch?v={video_id}"},
            headers=headers,
        )
        assert response.status_code == 201, response.text

    response = client.get(
        PARTICIPANTS_URL.format(session_id=session_body["id"]), headers=headers
    )
    assert response.status_code == 200, response.text
    entries = response.json()[0]["entries"]
    assert [entry["round_number"] for entry in entries] == [1, 2]
    assert entries[0]["position"] == 1
    assert entries[1]["position"] is None


def test_host_add_song_rejects_unknown_participant(client: TestClient) -> None:
    session_body, headers = _create_session(client)
    response = client.post(
        PARTICIPANT_ENTRIES_URL.format(
            session_id=session_body["id"], participant_id=uuid.uuid4()
        ),
        json={"youtube_url": WATCH_URL},
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "participant not found"


def test_host_create_and_add_reject_ended_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_body, headers = _create_session(client)
    participant = _create_host_participant(client, session_body["id"], headers)
    ended = client.post(f"{SESSIONS_URL}/{session_body['id']}/end", headers=headers)
    assert ended.status_code == 200, ended.text

    create = client.post(
        PARTICIPANTS_URL.format(session_id=session_body["id"]),
        json={"nickname": "Late"},
        headers=headers,
    )
    assert create.status_code == 409

    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        return _sample_metadata()

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)
    add = client.post(
        PARTICIPANT_ENTRIES_URL.format(
            session_id=session_body["id"], participant_id=participant["id"]
        ),
        json={"youtube_url": WATCH_URL},
        headers=headers,
    )
    assert add.status_code == 409


def test_host_participant_create_and_add_broadcast_events(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_body, headers = _create_session(client)
    host_token = headers["Authorization"].split(" ", maxsplit=1)[1]

    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        return _sample_metadata()

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)
    with client.websocket_connect(
        WS_URL.format(session_id=session_body["id"]) + f"?token={host_token}"
    ) as ws:
        participant = _create_host_participant(client, session_body["id"], headers)
        joined_event = ws.receive_json()
        assert joined_event["type"] == "ParticipantJoined"
        assert joined_event["nickname"] == "No Phone Nina"

        added = client.post(
            PARTICIPANT_ENTRIES_URL.format(
                session_id=session_body["id"], participant_id=participant["id"]
            ),
            json={"youtube_url": WATCH_URL},
            headers=headers,
        )
        assert added.status_code == 201, added.text
        queue_event = ws.receive_json()
        assert queue_event["type"] == "QueueUpdated"
        assert queue_event["snapshot"]["queue"][0]["participant_name"] == "No Phone Nina"
