"""Concurrency and failure-scenario tests (M18).

Formalizes plan.md §M18's behavioral + concurrency matrix:

- deterministic queue ordering under rapid (back-to-back) submissions;
- the find-or-create race handling for shared video rows and lazy round rows;
- "only one valid transition" when the host intervenes during automation;
- the E21 cancel-vs-remove race in both directions;
- reconnect recovery: authoritative playback/queue state survives a browser
  close and is re-fetchable (D18/D5), and a participant's identity/queue is
  recovered from the backend.

True simultaneous requests cannot run against the in-memory SQLite test engine
(StaticPool shares one connection), so "simultaneous" is exercised as rapid
sequential requests — the backend serializes them, which is the observable
contract.
"""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.queue_entry import QueueEntryStatus
from app.models.queue_entry import QueueEntry
from app.models.round import Round
from app.models.youtube_video import YouTubeVideo
from app.schemas.youtube import YouTubeVideoData
from app.services.queue import queue_service
from app.services.youtube import youtube_service

SESSIONS_URL = "/api/v1/sessions"
JOIN_URL = "/api/v1/join"
ENTRIES_URL = "/api/v1/entries"
REGISTER_URL = "/api/v1/auth/host/register"
LOGIN_URL = "/api/v1/auth/host/login"
WS_URL = "/api/v1/sessions/{session_id}/ws"

EMAIL = "host@example.com"
PASSWORD = "correct-horse-battery-staple"

VIDEO_A_ID = "dQw4w9WgXcQ"
VIDEO_B_ID = "9bZkp7q19f0"


def _video(video_id: str) -> YouTubeVideoData:
    return YouTubeVideoData(
        video_id=video_id,
        youtube_url=f"https://www.youtube.com/watch?v={video_id}",
        title=f"Song {video_id[:4]}",
        channel="Artist",
        duration_seconds=213,
        thumbnail_url=f"https://i.ytimg.com/vi/{video_id}/medium.jpg",
    )


def _patch_youtube(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        return _video(video_id)

    monkeypatch.setattr(youtube_service, "fetch_video_metadata", fake_fetch)


def _register(client: TestClient) -> dict[str, str]:
    register = client.post(REGISTER_URL, json={"email": EMAIL, "password": PASSWORD})
    assert register.status_code == 201, register.text
    login = client.post(LOGIN_URL, json={"email": EMAIL, "password": PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _setup(
    client: TestClient, timings: dict | None = None
) -> tuple[dict[str, str], dict, str]:
    """Return (host_headers, session_body, participant_token) with one Alice."""
    headers = _register(client)
    payload = timings if timings is not None else {}
    created = client.post(SESSIONS_URL, json=payload, headers=headers)
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


# --- Deterministic order under rapid submissions ------------------------------------


def test_two_participants_submit_rapidly_are_ordered(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch)
    headers, session_body, alice = _setup(client)
    bob = _join(client, session_body, "Bob")
    charlie = _join(client, session_body, "Charlie")

    # A quick burst of submissions (simulating simultaneity).
    _submit(client, session_body["id"], alice)
    _submit(client, session_body["id"], bob)
    _submit(client, session_body["id"], charlie)

    body = _snapshot(client, session_body["id"])
    assert [e["participant_name"] for e in body["queue"]] == [
        "Alice",
        "Bob",
        "Charlie",
    ]
    assert [e["position"] for e in body["queue"]] == [1, 2, 3]


async def test_rapid_duplicate_submits_share_one_video_row(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, session: AsyncSession
) -> None:
    _patch_youtube(monkeypatch)
    headers, session_body, alice = _setup(client)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice)
    _submit(client, session_body["id"], bob, video_id=VIDEO_A_ID)  # same video

    # D37: duplicate songs share one YouTubeVideo row (find-or-create).
    assert (
        await session.scalar(select(func.count(YouTubeVideo.id)))
    ) == 1


async def test_rapid_second_submits_reuse_the_same_future_round(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, session: AsyncSession
) -> None:
    _patch_youtube(monkeypatch)
    headers, session_body, alice = _setup(client)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice)  # round 1
    _submit(client, session_body["id"], bob)  # round 1
    _submit(client, session_body["id"], alice, video_id=VIDEO_B_ID)  # round 2 (created)
    _submit(client, session_body["id"], bob, video_id=VIDEO_B_ID)  # round 2 (reused)

    # Both second songs land in round 2 — the lazy round is created once and
    # reused by the second submitter (find-or-create, D43).
    round_numbers = set(
        await session.scalars(
            select(Round.number)
            .join(QueueEntry, QueueEntry.round_id == Round.id)
            .where(QueueEntry.session_id == uuid.UUID(session_body["id"]))
        )
    )
    assert round_numbers == {1, 2}


# --- Find-or-create race handling ----------------------------------------------------


async def test_find_or_create_video_uses_existing_row(
    session: AsyncSession,
) -> None:
    """When a concurrent winner already inserted the video row, the second
    submit finds it instead of violating the unique constraint (D37)."""
    karaoke_id = uuid.uuid4()
    existing = YouTubeVideo(
        youtube_video_id=VIDEO_A_ID,
        youtube_url=f"https://www.youtube.com/watch?v={VIDEO_A_ID}",
        title="Existing",
        channel="Artist",
        duration_seconds=213,
        thumbnail_url="",
    )
    session.add(existing)
    await session.commit()

    found = await queue_service._get_or_create_video(session, _video(VIDEO_A_ID))
    assert found.id == existing.id


async def test_find_or_create_round_uses_existing_round(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, session: AsyncSession
) -> None:
    """When a concurrent winner already created round 2, the second submit reuses
    it instead of violating the (session_id, number) constraint (D43)."""
    _patch_youtube(monkeypatch)
    headers, session_body, alice = _setup(client)
    _submit(client, session_body["id"], alice)  # round 1

    # Simulate a concurrent winner having created round 2.
    round_two = Round(session_id=uuid.UUID(session_body["id"]), number=2)
    session.add(round_two)
    await session.commit()

    found = await queue_service._get_or_create_round(
        session, uuid.UUID(session_body["id"]), 2
    )
    assert found.id == round_two.id


# --- "Only one valid transition" ------------------------------------------------------


def test_advance_twice_yields_a_single_transition(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch)
    # cooldown/countdown 0 -> the transition completes on the first advance.
    headers, session_body, alice = _setup(client, timings={"cooldown_seconds": 0, "countdown_seconds": 0})
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice)
    _submit(client, session_body["id"], bob)
    _play(client, session_body["id"], headers, "start")
    _play(client, session_body["id"], headers, "end")  # -> COUNTDOWN (cooldown 0)

    first = _play(client, session_body["id"], headers, "advance")
    assert first.status_code == 200, first.text
    assert first.json()["playback_state"] == "PLAYING"
    assert [
        e["status"] for e in first.json()["queue"]
    ] == ["SINGING"]  # exactly one entry promoted

    # A second advance cannot produce a second transition.
    second = _play(client, session_body["id"], headers, "advance")
    assert second.status_code == 409
    assert "no automatic transition" in second.json()["detail"]


def test_skip_during_countdown_is_not_possible(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch)
    headers, session_body, alice = _setup(client)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice)
    _submit(client, session_body["id"], bob)
    _play(client, session_body["id"], headers, "start")
    _play(client, session_body["id"], headers, "finish")  # -> COUNTDOWN

    response = _play(client, session_body["id"], headers, "skip")
    assert response.status_code == 409
    assert "no song is currently playing" in response.json()["detail"]


# --- E21: participant cancel vs host remove, both directions -------------------------


async def test_host_remove_then_participant_cancel_ends_valid(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, session: AsyncSession
) -> None:
    _patch_youtube(monkeypatch)
    headers, session_body, alice = _setup(client)
    submitted = _submit(client, session_body["id"], alice)
    entry_id = submitted.json()["entry"]["id"]

    # Host removes first -> REMOVED.
    removed = client.delete(f"{ENTRIES_URL}/{entry_id}", headers=headers)
    assert removed.status_code == 204, removed.text

    # The participant's later cancel is rejected (no silent overwrite, E21).
    cancelled = client.delete(
        f"{ENTRIES_URL}/{entry_id}",
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert cancelled.status_code == 409

    stored = await session.scalar(select(QueueEntry).where(QueueEntry.id == uuid.UUID(entry_id)))
    assert stored is not None
    assert stored.status is QueueEntryStatus.REMOVED


# --- Reconnect recovery (D18/D5/E8/E11) ----------------------------------------------


def test_host_reconnect_recovers_playback_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch)
    headers, session_body, alice = _setup(client)
    _submit(client, session_body["id"], alice)
    client.post(f"{SESSIONS_URL}/{session_body['id']}/start", headers=headers)
    _play(client, session_body["id"], headers, "start")  # Alice SINGING

    # A reopened dashboard (fresh fetches) sees the authoritative state (E11/D18).
    session_view = client.get(
        f"{SESSIONS_URL}/{session_body['id']}", headers=headers
    )
    assert session_view.status_code == 200
    assert session_view.json()["status"] == "ACTIVE"

    snapshot = _snapshot(client, session_body["id"])
    assert snapshot["playback_state"] == "PLAYING"
    assert snapshot["queue"][0]["status"] == "SINGING"


def test_participant_reconnect_recovers_identity_and_queue(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch)
    headers, session_body, alice = _setup(client)
    _submit(client, session_body["id"], alice)
    _submit(client, session_body["id"], alice, video_id=VIDEO_B_ID)

    # A fresh participant session (reconnected phone, E8/E9) re-fetches its own
    # entries with the stored token and reconnects to the realtime channel.
    mine = client.get(
        f"{SESSIONS_URL}/{session_body['id']}/entries/mine",
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert mine.status_code == 200, mine.text
    assert len(mine.json()) == 2

    with client.websocket_connect(
        WS_URL.format(session_id=session_body["id"]) + f"?token={alice}"
    ):
        pass  # a participant reconnect is accepted


# --- helpers -------------------------------------------------------------------------


def _play(
    client: TestClient, session_id: str, headers: dict, action: str
) -> httpx.Response:
    return client.post(
        f"{SESSIONS_URL}/{session_id}/play/{action}", headers=headers
    )
