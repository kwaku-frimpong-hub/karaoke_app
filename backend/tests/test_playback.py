"""Tests for the M11 playback state machine and the M13 automatic transitions.

Covers the host playback endpoints (start/end/skip/finish/advance/pause/
resume), the entry status lifecycle (WAITING -> SINGING -> COMPLETED/SKIPPED,
with NEXT promotion), the stored playback state + transition deadlines (M13,
D47), round auto-advance, the realtime singer events, and authorization.

The transition-clock tests use a frozen ``datetime`` in the playback service so
deadlines can be advanced deterministically without sleeping.
"""

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.queue_entry import QueueEntryStatus
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
VIDEO_B_ID = "9bZkp7q19f0"


class _FrozenDatetime:
    """Frozen ``datetime`` for the playback service clock (M13 tests)."""

    _now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls._now if tz is None else cls._now.astimezone(tz)

    @classmethod
    def advance(cls, seconds: int) -> None:
        cls._now += timedelta(seconds=seconds)


def _video(video_id: str, title: str) -> YouTubeVideoData:
    return YouTubeVideoData(
        video_id=video_id,
        youtube_url=f"https://www.youtube.com/watch?v={video_id}",
        title=title,
        channel="Artist",
        duration_seconds=213,
        thumbnail_url=f"https://i.ytimg.com/vi/{video_id}/medium.jpg",
    )


def _patch_youtube(
    monkeypatch: pytest.MonkeyPatch, videos: dict[str, YouTubeVideoData]
) -> None:
    async def fake_fetch(video_id: str) -> YouTubeVideoData:
        if video_id not in videos:
            raise YouTubeVideoUnavailableError(video_id)
        return videos[video_id]

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
    client: TestClient, session_id: str, token: str, video_id: str
) -> httpx.Response:
    return client.post(
        f"{SESSIONS_URL}/{session_id}/entries",
        json={"youtube_url": f"https://youtu.be/{video_id}"},
        headers={"Authorization": f"Bearer {token}"},
    )


def _play(client: TestClient, session_id: str, headers: dict, action: str) -> httpx.Response:
    return client.post(
        f"{SESSIONS_URL}/{session_id}/play/{action}", headers=headers
    )


def _snapshot(client: TestClient, session_id: str) -> dict:
    return client.get(f"{SESSIONS_URL}/{session_id}/entries").json()


# --- Authorization / ownership --------------------------------------------------


def test_playback_requires_host_authentication(client: TestClient) -> None:
    for action in ("start", "skip", "finish", "pause", "resume"):
        response = client.post(f"{SESSIONS_URL}/{uuid.uuid4()}/play/{action}")
        assert response.status_code == 401, action


def test_playback_by_non_owner_host_is_not_found(client: TestClient) -> None:
    _, session_body, _ = _setup(client, email=EMAIL)
    other_headers = _register(client, email=OTHER_EMAIL)
    response = _play(client, session_body["id"], other_headers, "start")
    assert response.status_code == 404


def test_playback_on_ended_session_conflicts(client: TestClient) -> None:
    headers, session_body, _ = _setup(client)
    client.post(f"{SESSIONS_URL}/{session_body['id']}/end", headers=headers)
    response = _play(client, session_body["id"], headers, "start")
    assert response.status_code == 409
    assert "ended" in response.json()["detail"]


# --- start ----------------------------------------------------------------------


def test_start_with_empty_queue_conflicts(client: TestClient) -> None:
    headers, session_body, _ = _setup(client)
    response = _play(client, session_body["id"], headers, "start")
    assert response.status_code == 409
    assert "empty" in response.json()["detail"]


def test_start_promotes_first_entry_and_derives_playing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(
        monkeypatch,
        {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A"), VIDEO_B_ID: _video(VIDEO_B_ID, "Song B")},
    )
    headers, session_body, alice = _setup(client)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice, VIDEO_A_ID)
    _submit(client, session_body["id"], bob, VIDEO_B_ID)

    assert _snapshot(client, session_body["id"])["playback_state"] == "IDLE"

    response = _play(client, session_body["id"], headers, "start")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["playback_state"] == "PLAYING"
    statuses = [e["status"] for e in body["queue"]]
    assert statuses == ["SINGING", "WAITING"]

    # The snapshot is authoritative: the same state appears on re-fetch.
    assert _snapshot(client, session_body["id"])["playback_state"] == "PLAYING"


def test_start_twice_conflicts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, token = _setup(client)
    _submit(client, session_body["id"], token, VIDEO_A_ID)
    assert _play(client, session_body["id"], headers, "start").status_code == 200
    response = _play(client, session_body["id"], headers, "start")
    assert response.status_code == 409
    assert "already playing" in response.json()["detail"]


# --- skip / finish ---------------------------------------------------------------


def test_skip_moves_singer_to_end_and_promotes_next(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(
        monkeypatch,
        {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A"), VIDEO_B_ID: _video(VIDEO_B_ID, "Song B")},
    )
    headers, session_body, alice = _setup(client)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice, VIDEO_A_ID)
    _submit(client, session_body["id"], bob, VIDEO_B_ID)
    started = _play(client, session_body["id"], headers, "start")
    assert started.status_code == 200
    singing_id = started.json()["queue"][0]["id"]

    response = _play(client, session_body["id"], headers, "skip")
    assert response.status_code == 200, response.text
    body = response.json()
    # Queue revision: the skipped singer is moved to the END of the round (one
    # re-chance), the next singer is promoted, and the countdown begins (no
    # cooldown on host intervention, D20).
    assert body["playback_state"] == "COUNTDOWN"
    assert body["transition_remaining_seconds"] is not None
    statuses = [e["status"] for e in body["queue"]]
    assert statuses == ["NEXT", "WAITING"]
    assert body["queue"][0]["participant_name"] == "Bob"
    # The skipped entry (Alice) is now last, still WAITING for a re-chance.
    assert body["queue"][-1]["id"] == singing_id
    assert body["queue"][-1]["participant_name"] == "Alice"


def test_finish_marks_completed_and_promotes_next(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(
        monkeypatch,
        {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A"), VIDEO_B_ID: _video(VIDEO_B_ID, "Song B")},
    )
    headers, session_body, alice = _setup(client)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice, VIDEO_A_ID)
    _submit(client, session_body["id"], bob, VIDEO_B_ID)
    _play(client, session_body["id"], headers, "start")

    response = _play(client, session_body["id"], headers, "finish")
    assert response.status_code == 200, response.text
    body = response.json()
    # M13: finish begins the countdown transition (no cooldown on host action).
    assert body["playback_state"] == "COUNTDOWN"
    assert [e["status"] for e in body["queue"]] == ["NEXT"]
    # The finished entry is terminal and dropped from the active queue.
    assert len(body["queue"]) == 1


def test_skip_finish_with_nothing_playing_conflicts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, token = _setup(client)
    _submit(client, session_body["id"], token, VIDEO_A_ID)

    for action in ("skip", "finish"):
        response = _play(client, session_body["id"], headers, action)
        assert response.status_code == 409
        assert "no song is currently playing" in response.json()["detail"]


def test_round_advances_after_finishing_last_entry(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(
        monkeypatch,
        {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A"), VIDEO_B_ID: _video(VIDEO_B_ID, "Song B")},
    )
    headers, session_body, alice = _setup(client)
    bob = _join(client, session_body, "Bob")
    # Round 1: Alice then Bob. Round 2: Alice's second song only.
    _submit(client, session_body["id"], alice, VIDEO_A_ID)
    _submit(client, session_body["id"], bob, VIDEO_A_ID)
    _submit(client, session_body["id"], alice, VIDEO_B_ID)

    first = _play(client, session_body["id"], headers, "start")
    assert first.status_code == 200
    assert first.json()["round_number"] == 1

    # Finish Alice's round-1 song: Bob becomes NEXT (still round 1).
    second = _play(client, session_body["id"], headers, "finish")
    assert second.status_code == 200
    assert second.json()["round_number"] == 1
    assert second.json()["queue"][0]["participant_name"] == "Bob"

    # Start + finish Bob's round-1 song: round 1 exhausted -> round 2 active,
    # and Alice's round-2 song is promoted to NEXT automatically (M10.1/M11).
    _play(client, session_body["id"], headers, "start")
    third = _play(client, session_body["id"], headers, "finish")
    assert third.status_code == 200, third.text
    assert third.json()["round_number"] == 2
    assert [e["participant_name"] for e in third.json()["queue"]] == ["Alice"]
    assert third.json()["queue"][0]["status"] == "NEXT"


# --- pause / resume ---------------------------------------------------------------


def test_pause_and_resume_transitions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, token = _setup(client)
    client.post(f"{SESSIONS_URL}/{session_body['id']}/start", headers=headers)

    paused = _play(client, session_body["id"], headers, "pause")
    assert paused.status_code == 200, paused.text
    assert paused.json()["status"] == "PAUSED"

    resumed = _play(client, session_body["id"], headers, "resume")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "ACTIVE"


def test_pause_requires_active_session(client: TestClient) -> None:
    headers, session_body, _ = _setup(client)  # still CREATED
    response = _play(client, session_body["id"], headers, "pause")
    assert response.status_code == 409
    assert "cannot be paused" in response.json()["detail"]


def test_resume_requires_paused_session(client: TestClient) -> None:
    headers, session_body, _ = _setup(client)
    client.post(f"{SESSIONS_URL}/{session_body['id']}/start", headers=headers)
    response = _play(client, session_body["id"], headers, "resume")
    assert response.status_code == 409
    assert "cannot be resumed" in response.json()["detail"]


# --- Realtime events ---------------------------------------------------------------


def test_start_broadcasts_singer_started_and_queue_updated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, token = _setup(client)
    _submit(client, session_body["id"], token, VIDEO_A_ID)
    host_token = headers["Authorization"].split(" ", maxsplit=1)[1]

    with client.websocket_connect(
        WS_URL.format(session_id=session_body["id"]) + f"?token={host_token}"
    ) as ws:
        response = _play(client, session_body["id"], headers, "start")
        assert response.status_code == 200, response.text
        first = ws.receive_json()
        second = ws.receive_json()
        types = {first["type"], second["type"]}
        assert types == {"SingerStarted", "QueueUpdated"}
        singer = next(e for e in (first, second) if e["type"] == "SingerStarted")
        assert singer["participant_name"] == "Alice"
        assert singer["title"] == "Song A"


def test_skip_broadcasts_singer_skipped(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, token = _setup(client)
    _submit(client, session_body["id"], token, VIDEO_A_ID)
    host_token = headers["Authorization"].split(" ", maxsplit=1)[1]

    with client.websocket_connect(
        WS_URL.format(session_id=session_body["id"]) + f"?token={host_token}"
    ) as ws:
        _play(client, session_body["id"], headers, "start")
        # Consume the two start events (SingerStarted + QueueUpdated).
        ws.receive_json()
        ws.receive_json()
        response = _play(client, session_body["id"], headers, "skip")
        assert response.status_code == 200, response.text
        events = {ws.receive_json()["type"], ws.receive_json()["type"]}
        assert "SingerSkipped" in events
        assert "QueueUpdated" in events


async def test_skip_only_singer_excludes_them_and_completes_round(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    session: AsyncSession,
) -> None:
    _patch_youtube(
        monkeypatch,
        {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A"), VIDEO_B_ID: _video(VIDEO_B_ID, "Song B")},
    )
    headers, session_body, alice = _setup(client)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice, VIDEO_A_ID)
    _submit(client, session_body["id"], bob, VIDEO_B_ID)
    started = _play(client, session_body["id"], headers, "start")
    singing_id = started.json()["queue"][0]["id"]

    # The host removes Bob's song, leaving Alice as the only singer.
    snapshot = _snapshot(client, session_body["id"])
    bob_entry = next(e for e in snapshot["queue"] if e["participant_name"] == "Bob")
    removed = client.delete(f"{ENTRIES_URL}/{bob_entry['id']}", headers=headers)
    assert removed.status_code == 204, removed.text

    # Skipping the only singer excludes them so the round can complete.
    response = _play(client, session_body["id"], headers, "skip")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["playback_state"] == "IDLE"
    assert body["queue"] == []

    stored = await session.scalar(
        select(QueueEntry).where(QueueEntry.id == uuid.UUID(singing_id))
    )
    assert stored is not None
    assert stored.status is QueueEntryStatus.SKIPPED


# --- Automatic transitions (M13) ---------------------------------------------------


def _setup_with_timings(
    client: TestClient,
    cooldown: int,
    countdown: int,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, str], dict, str]:
    """Like ``_setup`` but with a frozen clock and per-session timings."""
    monkeypatch.setattr("app.services.playback.datetime", _FrozenDatetime)
    headers = _register(client)
    created = client.post(
        SESSIONS_URL,
        json={"cooldown_seconds": cooldown, "countdown_seconds": countdown},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    session_body = created.json()
    joined = client.post(
        f"{JOIN_URL}/{session_body['join_code']}/participants",
        json={"nickname": "Alice"},
    )
    assert joined.status_code == 201, joined.text
    return headers, session_body, joined.json()["token"]


def test_end_begins_cooldown_transition(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, alice = _setup_with_timings(client, 10, 20, monkeypatch)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice, VIDEO_A_ID)
    _submit(client, session_body["id"], bob, VIDEO_A_ID)
    _play(client, session_body["id"], headers, "start")

    response = _play(client, session_body["id"], headers, "end")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["playback_state"] == "COOLDOWN"
    assert body["transition_until"] is not None
    assert body["transition_remaining_seconds"] is not None
    # The finished entry is terminal; the next is promoted to NEXT.
    assert [e["status"] for e in body["queue"]] == ["NEXT"]


def test_advance_moves_cooldown_then_countdown_then_auto_start(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, alice = _setup_with_timings(client, 10, 5, monkeypatch)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice, VIDEO_A_ID)
    _submit(client, session_body["id"], bob, VIDEO_A_ID)
    _play(client, session_body["id"], headers, "start")
    _play(client, session_body["id"], headers, "end")

    # Before the cooldown deadline: advance is rejected.
    early = _play(client, session_body["id"], headers, "advance")
    assert early.status_code == 409
    assert "cooldown is still running" in early.json()["detail"]

    # Past the cooldown deadline: COOLDOWN -> COUNTDOWN.
    _FrozenDatetime.advance(11)
    body = _play(client, session_body["id"], headers, "advance").json()
    assert body["playback_state"] == "COUNTDOWN"

    # Before the countdown deadline: rejected.
    early2 = _play(client, session_body["id"], headers, "advance")
    assert early2.status_code == 409
    assert "countdown is still running" in early2.json()["detail"]

    # Past the countdown deadline: the next entry auto-starts (PLAYING).
    _FrozenDatetime.advance(6)
    body = _play(client, session_body["id"], headers, "advance")
    assert body.status_code == 200, body.text
    json_body = body.json()
    assert json_body["playback_state"] == "PLAYING"
    assert json_body["transition_until"] is None
    assert [e["status"] for e in json_body["queue"]] == ["SINGING"]
    assert json_body["queue"][0]["participant_name"] == "Bob"


def test_advance_with_no_transition_conflicts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, token = _setup_with_timings(client, 10, 20, monkeypatch)
    _submit(client, session_body["id"], token, VIDEO_A_ID)
    _play(client, session_body["id"], headers, "start")
    response = _play(client, session_body["id"], headers, "advance")
    assert response.status_code == 409
    assert "no automatic transition" in response.json()["detail"]


def test_manual_start_cancels_pending_transition(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, alice = _setup_with_timings(client, 10, 20, monkeypatch)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice, VIDEO_A_ID)
    _submit(client, session_body["id"], bob, VIDEO_A_ID)
    _play(client, session_body["id"], headers, "start")
    _play(client, session_body["id"], headers, "finish")  # -> COUNTDOWN

    # The host manually starts the next song, cancelling the countdown.
    body = _play(client, session_body["id"], headers, "start")
    assert body.status_code == 200, body.text
    json_body = body.json()
    assert json_body["playback_state"] == "PLAYING"
    assert json_body["transition_until"] is None
    assert [e["status"] for e in json_body["queue"]] == ["SINGING"]


def test_pause_cancels_pending_transition(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, alice = _setup_with_timings(client, 10, 20, monkeypatch)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice, VIDEO_A_ID)
    _submit(client, session_body["id"], bob, VIDEO_A_ID)
    client.post(f"{SESSIONS_URL}/{session_body['id']}/start", headers=headers)
    _play(client, session_body["id"], headers, "start")
    _play(client, session_body["id"], headers, "end")  # -> COOLDOWN

    paused = _play(client, session_body["id"], headers, "pause")
    assert paused.status_code == 200, paused.text
    json_body = paused.json()
    assert json_body["status"] == "PAUSED"
    assert json_body["playback_state"] == "IDLE"
    assert json_body["transition_until"] is None
    # The NEXT entry waits for a manual start after resume (E22).
    assert [e["status"] for e in json_body["queue"]] == ["NEXT"]


def test_end_with_no_next_returns_idle(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, token = _setup_with_timings(client, 10, 20, monkeypatch)
    _submit(client, session_body["id"], token, VIDEO_A_ID)
    _play(client, session_body["id"], headers, "start")
    body = _play(client, session_body["id"], headers, "end")
    assert body.status_code == 200, body.text
    json_body = body.json()
    assert json_body["playback_state"] == "IDLE"
    assert json_body["transition_until"] is None
    assert json_body["queue"] == []


def test_transition_timings_are_per_session_and_instant_path(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, alice = _setup_with_timings(client, 0, 0, monkeypatch)
    bob = _join(client, session_body, "Bob")
    # The session response carries the per-session timings (PRODUCT_SPEC §10).
    assert session_body["cooldown_seconds"] == 0
    assert session_body["countdown_seconds"] == 0
    _submit(client, session_body["id"], alice, VIDEO_A_ID)
    _submit(client, session_body["id"], bob, VIDEO_A_ID)
    _play(client, session_body["id"], headers, "start")

    # With cooldown 0 the transition skips COOLDOWN and enters COUNTDOWN
    # immediately; with countdown 0 advance auto-starts right away.
    ended = _play(client, session_body["id"], headers, "end")
    assert ended.status_code == 200, ended.text
    assert ended.json()["playback_state"] == "COUNTDOWN"

    started = _play(client, session_body["id"], headers, "advance")
    assert started.status_code == 200, started.text
    assert started.json()["playback_state"] == "PLAYING"
    assert [e["status"] for e in started.json()["queue"]] == ["SINGING"]


def test_advance_after_queue_emptied_returns_idle(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Removing the NEXT entry mid-countdown must not leave PLAYING without a
    singer (D47 invariant)."""
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, alice = _setup_with_timings(client, 0, 0, monkeypatch)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice, VIDEO_A_ID)
    _submit(client, session_body["id"], bob, VIDEO_A_ID)
    _play(client, session_body["id"], headers, "start")
    finished = _play(client, session_body["id"], headers, "finish")  # -> COUNTDOWN
    assert finished.status_code == 200, finished.text
    next_id = finished.json()["queue"][0]["id"]

    # The host removes the NEXT entry while the countdown is pending.
    removed = client.delete(f"{ENTRIES_URL}/{next_id}", headers=headers)
    assert removed.status_code == 204, removed.text

    body = _play(client, session_body["id"], headers, "advance")
    assert body.status_code == 200, body.text
    json_body = body.json()
    assert json_body["playback_state"] == "IDLE"
    assert json_body["transition_until"] is None
    assert json_body["queue"] == []


def test_advance_broadcasts_singer_started_on_auto_start(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, alice = _setup_with_timings(client, 0, 0, monkeypatch)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice, VIDEO_A_ID)
    _submit(client, session_body["id"], bob, VIDEO_A_ID)
    host_token = headers["Authorization"].split(" ", maxsplit=1)[1]

    with client.websocket_connect(
        WS_URL.format(session_id=session_body["id"]) + f"?token={host_token}"
    ) as ws:
        _play(client, session_body["id"], headers, "start")
        # Consume start events (SingerStarted + QueueUpdated).
        ws.receive_json()
        ws.receive_json()
        _play(client, session_body["id"], headers, "end")  # -> COUNTDOWN (cooldown 0)
        # end emits: SingerFinished + QueueUpdated + NextSingerNotified(next)
        # + NextSingerNotified(countdown) since the countdown starts immediately.
        events = {ws.receive_json()["type"] for _ in range(4)}
        assert {"SingerFinished", "QueueUpdated", "NextSingerNotified"} <= events

        response = _play(client, session_body["id"], headers, "advance")
        assert response.status_code == 200, response.text
        events = {ws.receive_json()["type"], ws.receive_json()["type"]}
        assert "SingerStarted" in events
        assert "QueueUpdated" in events


# --- Next-singer notifications (M15) ----------------------------------------------


def _drain_events(ws, count: int) -> list[dict]:
    return [ws.receive_json() for _ in range(count)]


def _notifications(events: list[dict]) -> list[dict]:
    return [e for e in events if e["type"] == "NextSingerNotified"]


def test_end_broadcasts_next_singer_notification(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, alice = _setup_with_timings(client, 10, 20, monkeypatch)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice, VIDEO_A_ID)
    _submit(client, session_body["id"], bob, VIDEO_A_ID)
    host_token = headers["Authorization"].split(" ", maxsplit=1)[1]

    with client.websocket_connect(
        WS_URL.format(session_id=session_body["id"]) + f"?token={host_token}"
    ) as ws:
        _play(client, session_body["id"], headers, "start")
        _drain_events(ws, 2)  # SingerStarted + QueueUpdated

        _play(client, session_body["id"], headers, "end")  # -> COOLDOWN
        events = _drain_events(ws, 3)  # SingerFinished + QueueUpdated + notify
        notifications = _notifications(events)
        assert len(notifications) == 1
        notify = notifications[0]
        assert notify["phase"] == "next"
        assert notify["participant_name"] == "Bob"
        assert notify["title"] == "Song A"


def test_finish_broadcasts_next_singer_notification_both_phases(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, alice = _setup_with_timings(client, 10, 20, monkeypatch)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice, VIDEO_A_ID)
    _submit(client, session_body["id"], bob, VIDEO_A_ID)
    host_token = headers["Authorization"].split(" ", maxsplit=1)[1]

    with client.websocket_connect(
        WS_URL.format(session_id=session_body["id"]) + f"?token={host_token}"
    ) as ws:
        _play(client, session_body["id"], headers, "start")
        _drain_events(ws, 2)

        # finish -> COUNTDOWN immediately (no cooldown): notify both phases.
        _play(client, session_body["id"], headers, "finish")
        events = _drain_events(ws, 4)
        phases = {n["phase"] for n in _notifications(events)}
        assert phases == {"next", "countdown"}
        assert all(n["participant_name"] == "Bob" for n in _notifications(events))


def test_advance_to_countdown_broadcasts_notification(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, alice = _setup_with_timings(client, 10, 5, monkeypatch)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice, VIDEO_A_ID)
    _submit(client, session_body["id"], bob, VIDEO_A_ID)
    host_token = headers["Authorization"].split(" ", maxsplit=1)[1]

    with client.websocket_connect(
        WS_URL.format(session_id=session_body["id"]) + f"?token={host_token}"
    ) as ws:
        _play(client, session_body["id"], headers, "start")
        _drain_events(ws, 2)
        _play(client, session_body["id"], headers, "end")  # -> COOLDOWN
        _drain_events(ws, 3)  # SingerFinished + QueueUpdated + notify(next)

        # Past the cooldown deadline: COOLDOWN -> COUNTDOWN = countdown-start.
        _FrozenDatetime.advance(11)
        _play(client, session_body["id"], headers, "advance")
        events = _drain_events(ws, 2)  # QueueUpdated + notify(countdown)
        notifications = _notifications(events)
        assert len(notifications) == 1
        assert notifications[0]["phase"] == "countdown"
        assert notifications[0]["participant_name"] == "Bob"


def test_remove_singer_broadcasts_notification(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, alice = _setup_with_timings(client, 10, 20, monkeypatch)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice, VIDEO_A_ID)
    _submit(client, session_body["id"], bob, VIDEO_A_ID)
    host_token = headers["Authorization"].split(" ", maxsplit=1)[1]

    with client.websocket_connect(
        WS_URL.format(session_id=session_body["id"]) + f"?token={host_token}"
    ) as ws:
        started = _play(client, session_body["id"], headers, "start")
        _drain_events(ws, 2)
        singing_id = started.json()["queue"][0]["id"]

        removed = client.delete(f"{ENTRIES_URL}/{singing_id}", headers=headers)
        assert removed.status_code == 204, removed.text
        events = _drain_events(ws, 3)  # QueueUpdated + notify(next) + notify(countdown)
        phases = {n["phase"] for n in _notifications(events)}
        assert phases == {"next", "countdown"}
        assert all(n["participant_name"] == "Bob" for n in _notifications(events))


# --- Host moderation (M14) --------------------------------------------------------


def test_remove_current_singer_advances_playback(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, alice = _setup_with_timings(client, 10, 20, monkeypatch)
    bob = _join(client, session_body, "Bob")
    _submit(client, session_body["id"], alice, VIDEO_A_ID)
    _submit(client, session_body["id"], bob, VIDEO_A_ID)
    started = _play(client, session_body["id"], headers, "start")
    singing_id = started.json()["queue"][0]["id"]

    removed = client.delete(f"{ENTRIES_URL}/{singing_id}", headers=headers)
    assert removed.status_code == 204, removed.text

    body = _snapshot(client, session_body["id"])
    # E6: removing the current singer advances playback — the next entry is
    # promoted and the countdown transition begins (host intervention skips the
    # cooldown, D20).
    assert body["playback_state"] == "COUNTDOWN"
    assert body["transition_until"] is not None
    assert [e["status"] for e in body["queue"]] == ["NEXT"]
    assert body["queue"][0]["participant_name"] == "Bob"


def test_remove_current_singer_only_entry_returns_idle(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, token = _setup_with_timings(client, 10, 20, monkeypatch)
    _submit(client, session_body["id"], token, VIDEO_A_ID)
    started = _play(client, session_body["id"], headers, "start")
    singing_id = started.json()["queue"][0]["id"]

    removed = client.delete(f"{ENTRIES_URL}/{singing_id}", headers=headers)
    assert removed.status_code == 204, removed.text

    body = _snapshot(client, session_body["id"])
    assert body["playback_state"] == "IDLE"
    assert body["transition_until"] is None
    assert body["queue"] == []


def test_remove_next_entry_mid_countdown_self_heals(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, alice = _setup_with_timings(client, 0, 0, monkeypatch)
    bob = _join(client, session_body, "Bob")
    charlie = _join(client, session_body, "Charlie")
    _submit(client, session_body["id"], alice, VIDEO_A_ID)
    _submit(client, session_body["id"], bob, VIDEO_A_ID)
    _submit(client, session_body["id"], charlie, VIDEO_A_ID)
    _play(client, session_body["id"], headers, "start")
    finished = _play(client, session_body["id"], headers, "finish")  # -> COUNTDOWN
    next_id = finished.json()["queue"][0]["id"]
    assert finished.json()["queue"][0]["participant_name"] == "Bob"

    # The host removes the NEXT entry during the countdown.
    removed = client.delete(f"{ENTRIES_URL}/{next_id}", headers=headers)
    assert removed.status_code == 204, removed.text

    # Advancing past the deadline starts the NEW front (Charlie) — self-healing.
    body = _play(client, session_body["id"], headers, "advance")
    assert body.status_code == 200, body.text
    json_body = body.json()
    assert json_body["playback_state"] == "PLAYING"
    assert [e["participant_name"] for e in json_body["queue"]] == ["Charlie"]
    assert json_body["queue"][0]["status"] == "SINGING"


async def test_remove_terminal_entry_is_noop(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, session: AsyncSession
) -> None:
    """E21: removing an already-terminal entry is a no-op (does not overwrite
    the CANCELLED status with REMOVED)."""
    _patch_youtube(monkeypatch, {VIDEO_A_ID: _video(VIDEO_A_ID, "Song A")})
    headers, session_body, token = _setup(client)
    submitted = _submit(client, session_body["id"], token, VIDEO_A_ID)
    entry_id = submitted.json()["entry"]["id"]

    # The participant cancels first -> CANCELLED.
    cancelled = client.delete(
        f"{ENTRIES_URL}/{entry_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert cancelled.status_code == 204, cancelled.text

    # The host then removes the same entry -> no-op (204, status preserved).
    removed = client.delete(f"{ENTRIES_URL}/{entry_id}", headers=headers)
    assert removed.status_code == 204, removed.text

    stored = await session.scalar(select(QueueEntry).where(QueueEntry.id == uuid.UUID(entry_id)))
    assert stored is not None
    assert stored.status is QueueEntryStatus.CANCELLED
