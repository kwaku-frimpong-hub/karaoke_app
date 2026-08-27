"""Tests for the host's per-round reorder (queue revision).

Join order is the default; the host can reorder the current round via
``PATCH /api/v1/sessions/{id}/order`` and reset it with ``DELETE``. Reorder is
per-round only — the next round falls back to join order.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.schemas.youtube import YouTubeVideoData
from app.services.youtube import (
    YouTubeVideoUnavailableError,
    youtube_service,
)

SESSIONS_URL = "/api/v1/sessions"
JOIN_URL = "/api/v1/join"
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


def _setup(client: TestClient) -> tuple[dict[str, str], dict]:
    headers = _register(client)
    created = client.post(SESSIONS_URL, json={}, headers=headers)
    assert created.status_code == 201, created.text
    return headers, created.json()


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


def _queue_names(client: TestClient, session_id: str) -> list[str]:
    return [e["participant_name"] for e in _snapshot(client, session_id)["queue"]]


def _three_singers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, str], dict]:
    """A session with Alice, Bob, Charlie (join order) each with one song."""
    _patch_youtube(monkeypatch)
    headers, session_body = _setup(client)
    for nickname in ("Alice", "Bob", "Charlie"):
        token = _join(client, session_body, nickname)
        _submit(client, session_body["id"], token)
    return headers, session_body


# --- Authorization / validation -----------------------------------------------------


def test_reorder_requires_host_authentication(client: TestClient) -> None:
    assert client.patch(f"{SESSIONS_URL}/some-id/order", json={"participant_names": ["A"]}).status_code == 401
    assert client.delete(f"{SESSIONS_URL}/some-id/order").status_code == 401


def test_reorder_by_non_owner_host_is_not_found(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch)
    headers, session_body = _setup(client)
    other = _register(client, email=OTHER_EMAIL)
    response = client.patch(
        f"{SESSIONS_URL}/{session_body['id']}/order",
        json={"participant_names": ["Alice"]},
        headers=other,
    )
    assert response.status_code == 404


def test_reorder_unknown_name_is_unprocessable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, session_body = _three_singers(client, monkeypatch)
    response = client.patch(
        f"{SESSIONS_URL}/{session_body['id']}/order",
        json={"participant_names": ["Ghost"]},
        headers=headers,
    )
    assert response.status_code == 422
    assert "unknown participant" in response.json()["detail"]


def test_reorder_duplicate_name_is_unprocessable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, session_body = _three_singers(client, monkeypatch)
    response = client.patch(
        f"{SESSIONS_URL}/{session_body['id']}/order",
        json={"participant_names": ["Alice", "Alice", "Bob"]},
        headers=headers,
    )
    assert response.status_code == 422
    assert "unique" in response.json()["detail"]


def test_reorder_empty_queue_is_unprocessable(client: TestClient) -> None:
    headers, session_body = _setup(client)
    response = client.patch(
        f"{SESSIONS_URL}/{session_body['id']}/order",
        json={"participant_names": ["Alice"]},
        headers=headers,
    )
    assert response.status_code == 422
    assert "empty" in response.json()["detail"]


# --- Behavior ------------------------------------------------------------------------


def test_reorder_changes_current_round_order(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, session_body = _three_singers(client, monkeypatch)
    assert _queue_names(client, session_body["id"]) == ["Alice", "Bob", "Charlie"]

    response = client.patch(
        f"{SESSIONS_URL}/{session_body['id']}/order",
        json={"participant_names": ["Charlie", "Alice", "Bob"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert [e["participant_name"] for e in response.json()["queue"]] == [
        "Charlie",
        "Alice",
        "Bob",
    ]
    # The snapshot (authoritative state) reflects it too.
    assert _queue_names(client, session_body["id"]) == ["Charlie", "Alice", "Bob"]


def test_reset_restores_join_order(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, session_body = _three_singers(client, monkeypatch)
    client.patch(
        f"{SESSIONS_URL}/{session_body['id']}/order",
        json={"participant_names": ["Charlie", "Bob", "Alice"]},
        headers=headers,
    )
    assert _queue_names(client, session_body["id"]) == ["Charlie", "Bob", "Alice"]

    response = client.delete(
        f"{SESSIONS_URL}/{session_body['id']}/order", headers=headers
    )
    assert response.status_code == 200, response.text
    assert _queue_names(client, session_body["id"]) == ["Alice", "Bob", "Charlie"]


def test_reorder_is_per_round(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The next round falls back to join order (per-round reorder)."""
    headers, session_body = _three_singers(client, monkeypatch)
    client.patch(
        f"{SESSIONS_URL}/{session_body['id']}/order",
        json={"participant_names": ["Charlie", "Alice", "Bob"]},
        headers=headers,
    )
    assert _queue_names(client, session_body["id"]) == ["Charlie", "Alice", "Bob"]

    # Exhaust round 1 (host removes every entry) -> round 2 has no entries here,
    # so instead verify against the next round Alice/Bob actually have: give
    # Alice and Bob round-2 songs, then exhaust round 1.
    round_one = _snapshot(client, session_body["id"])["queue"]
    for entry in round_one:
        assert client.delete(
            f"/api/v1/entries/{entry['id']}", headers=headers
        ).status_code == 204

    # Charlie already used his reorder; Alice/Bob get round-2 songs and the
    # round-2 order must be join order (Alice, Bob) — NOT the reorder.
    alice = _join(client, session_body, "Alice2")
    bob = _join(client, session_body, "Bob2")
    _submit(client, session_body["id"], alice)
    _submit(client, session_body["id"], bob)
    assert _queue_names(client, session_body["id"]) == ["Alice2", "Bob2"]


def test_reorder_broadcasts_queue_updated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_youtube(monkeypatch)
    headers, session_body = _three_singers(client, monkeypatch)
    host_token = headers["Authorization"].split(" ", maxsplit=1)[1]

    with client.websocket_connect(
        WS_URL.format(session_id=session_body["id"]) + f"?token={host_token}"
    ) as ws:
        response = client.patch(
            f"{SESSIONS_URL}/{session_body['id']}/order",
            json={"participant_names": ["Charlie", "Bob", "Alice"]},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        event = ws.receive_json()
        assert event["type"] == "QueueUpdated"
        assert [e["participant_name"] for e in event["snapshot"]["queue"]] == [
            "Charlie",
            "Bob",
            "Alice",
        ]
