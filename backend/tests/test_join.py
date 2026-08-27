"""Tests for the public join flow (M5).

Covers public session lookup by join code, participant registration, nickname
rules (B14/D16), ended-session rejection, and token hygiene at rest.
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_auth_token
from app.domain.session import SessionStatus
from app.models.participant import Participant
from app.models.session import Session

JOIN_URL = "/api/v1/join"
REGISTER_URL = "/api/v1/auth/host/register"
LOGIN_URL = "/api/v1/auth/host/login"
SESSIONS_URL = "/api/v1/sessions"

EMAIL = "host@example.com"
PASSWORD = "correct-horse-battery-staple"


def _create_session(
    client: TestClient, email: str = EMAIL
) -> tuple[dict[str, str], dict]:
    """Register+login a host and create a session; return (headers, body)."""
    register = client.post(REGISTER_URL, json={"email": email, "password": PASSWORD})
    assert register.status_code == 201, register.text
    login = client.post(LOGIN_URL, json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    created = client.post(SESSIONS_URL, json={}, headers=headers)
    assert created.status_code == 201, created.text
    return headers, created.json()


def _end_session(client: TestClient, headers: dict[str, str], session_id: str) -> None:
    response = client.post(f"{SESSIONS_URL}/{session_id}/end", headers=headers)
    assert response.status_code == 200, response.text


# --- Public lookup ------------------------------------------------------------


def test_lookup_requires_no_authentication(client: TestClient) -> None:
    _, session_body = _create_session(client)
    response = client.get(f"{JOIN_URL}/{session_body['join_code']}")
    assert response.status_code == 200


def test_lookup_returns_public_snapshot(client: TestClient) -> None:
    _, session_body = _create_session(client)
    response = client.get(f"{JOIN_URL}/{session_body['join_code']}")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "id": session_body["id"],
        "name": session_body["name"],
        "status": SessionStatus.CREATED.value,
    }


def test_lookup_unknown_code_is_not_found(client: TestClient) -> None:
    response = client.get(f"{JOIN_URL}/ZZZZZZ")
    assert response.status_code == 404


def test_lookup_is_case_insensitive(client: TestClient) -> None:
    _, session_body = _create_session(client)
    lower = session_body["join_code"].lower()
    response = client.get(f"{JOIN_URL}/{lower}")
    assert response.status_code == 200
    assert response.json()["id"] == session_body["id"]


def test_lookup_ended_session_still_returns_snapshot(client: TestClient) -> None:
    headers, session_body = _create_session(client)
    _end_session(client, headers, session_body["id"])
    response = client.get(f"{JOIN_URL}/{session_body['join_code']}")
    assert response.status_code == 200
    assert response.json()["status"] == SessionStatus.ENDED.value


# --- Participant registration ---------------------------------------------------


def test_register_requires_no_authentication(client: TestClient) -> None:
    _, session_body = _create_session(client)
    response = client.post(
        f"{JOIN_URL}/{session_body['join_code']}/participants",
        json={"nickname": "Alice"},
    )
    assert response.status_code == 201


def test_register_returns_token_session_and_participant(client: TestClient) -> None:
    _, session_body = _create_session(client)
    response = client.post(
        f"{JOIN_URL}/{session_body['join_code']}/participants",
        json={"nickname": "Alice"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["token"]
    assert body["token_type"] == "bearer"
    assert body["session"] == {
        "id": session_body["id"],
        "name": session_body["name"],
        "status": SessionStatus.CREATED.value,
    }
    assert body["participant"]["nickname"] == "Alice"
    assert body["participant"]["session_id"] == session_body["id"]
    assert uuid.UUID(body["participant"]["id"])
    assert "created_at" in body["participant"]


def test_register_unknown_code_is_not_found(client: TestClient) -> None:
    response = client.post(
        f"{JOIN_URL}/ZZZZZZ/participants", json={"nickname": "Alice"}
    )
    assert response.status_code == 404


def test_register_ended_session_conflicts(client: TestClient) -> None:
    headers, session_body = _create_session(client)
    _end_session(client, headers, session_body["id"])
    response = client.post(
        f"{JOIN_URL}/{session_body['join_code']}/participants",
        json={"nickname": "Alice"},
    )
    assert response.status_code == 409
    assert "ended" in response.json()["detail"]


def test_register_blank_nickname_is_unprocessable(client: TestClient) -> None:
    _, session_body = _create_session(client)
    response = client.post(
        f"{JOIN_URL}/{session_body['join_code']}/participants",
        json={"nickname": "   "},
    )
    assert response.status_code == 422


def test_register_overlong_nickname_is_unprocessable(client: TestClient) -> None:
    _, session_body = _create_session(client)
    response = client.post(
        f"{JOIN_URL}/{session_body['join_code']}/participants",
        json={"nickname": "x" * 21},
    )
    assert response.status_code == 422


def test_register_duplicate_nickname_case_insensitive_conflicts(
    client: TestClient,
) -> None:
    _, session_body = _create_session(client)
    first = client.post(
        f"{JOIN_URL}/{session_body['join_code']}/participants",
        json={"nickname": "Emma"},
    )
    assert first.status_code == 201

    second = client.post(
        f"{JOIN_URL}/{session_body['join_code']}/participants",
        json={"nickname": "emma"},
    )
    assert second.status_code == 409
    assert "already taken" in second.json()["detail"]


def test_register_same_nickname_different_sessions_ok(client: TestClient) -> None:
    _, first = _create_session(client, email=EMAIL)
    _, second = _create_session(client, email="other@example.com")
    for session_body in (first, second):
        response = client.post(
            f"{JOIN_URL}/{session_body['join_code']}/participants",
            json={"nickname": "Alice"},
        )
        assert response.status_code == 201, response.text


def test_register_trims_nickname(client: TestClient) -> None:
    _, session_body = _create_session(client)
    response = client.post(
        f"{JOIN_URL}/{session_body['join_code']}/participants",
        json={"nickname": "  Alice  "},
    )
    assert response.status_code == 201
    assert response.json()["participant"]["nickname"] == "Alice"


# --- Persistence / hygiene -------------------------------------------------------


async def test_register_persists_participant(
    client: TestClient, session: AsyncSession
) -> None:
    _, session_body = _create_session(client)
    client.post(
        f"{JOIN_URL}/{session_body['join_code']}/participants",
        json={"nickname": "Emma"},
    )

    stored = await session.scalar(select(Participant))
    assert stored is not None
    assert stored.session_id == uuid.UUID(session_body["id"])
    assert stored.nickname == "Emma"
    assert stored.nickname_lower == "emma"


async def test_register_token_is_stored_hashed(
    client: TestClient, session: AsyncSession
) -> None:
    _, session_body = _create_session(client)
    response = client.post(
        f"{JOIN_URL}/{session_body['join_code']}/participants",
        json={"nickname": "Alice"},
    )
    raw_token = response.json()["token"]

    stored = await session.scalar(select(Participant))
    assert stored is not None
    assert stored.token_hash != raw_token
    assert stored.token_hash == hash_auth_token(raw_token)


async def test_register_participant_belongs_to_session(
    client: TestClient, session: AsyncSession
) -> None:
    headers, session_body = _create_session(client)
    client.post(
        f"{JOIN_URL}/{session_body['join_code']}/participants",
        json={"nickname": "Alice"},
    )

    karaoke = await session.scalar(
        select(Session).where(Session.id == uuid.UUID(session_body["id"]))
    )
    assert karaoke is not None
    participant_count = (
        await session.scalar(
            select(Participant.id).where(Participant.session_id == karaoke.id)
        )
    )
    assert participant_count is not None
