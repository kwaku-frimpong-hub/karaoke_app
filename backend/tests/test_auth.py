"""Integration tests for host authentication (M3).

Covers registration, login, logout, token protection of host endpoints, and
token/credential hygiene at rest.
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_auth_token
from app.models.host import Host
from app.models.host_auth_token import HostAuthToken

REGISTER_URL = "/api/v1/auth/host/register"
LOGIN_URL = "/api/v1/auth/host/login"
LOGOUT_URL = "/api/v1/auth/host/logout"
ME_URL = "/api/v1/auth/host/me"

EMAIL = "host@example.com"
OTHER_EMAIL = "other@example.com"
PASSWORD = "correct-horse-battery-staple"


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register(client: TestClient, email: str = EMAIL, password: str = PASSWORD) -> None:
    response = client.post(REGISTER_URL, json={"email": email, "password": password})
    assert response.status_code == 201, response.text


def _login(client: TestClient, email: str = EMAIL, password: str = PASSWORD) -> dict:
    response = client.post(LOGIN_URL, json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


# --- Registration -----------------------------------------------------------


def test_register_creates_host(client: TestClient) -> None:
    response = client.post(
        REGISTER_URL, json={"email": EMAIL, "password": PASSWORD}
    )
    assert response.status_code == 201
    body = response.json()
    assert uuid.UUID(body["id"])
    assert body["email"] == EMAIL
    assert "created_at" in body


def test_register_normalizes_email_case(client: TestClient) -> None:
    response = client.post(
        REGISTER_URL, json={"email": "Host@Example.COM", "password": PASSWORD}
    )
    assert response.status_code == 201
    assert response.json()["email"] == EMAIL


def test_register_duplicate_email_conflicts_case_insensitive(client: TestClient) -> None:
    _register(client)
    response = client.post(
        REGISTER_URL, json={"email": "HOST@EXAMPLE.COM", "password": PASSWORD}
    )
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_register_rejects_invalid_email(client: TestClient) -> None:
    response = client.post(REGISTER_URL, json={"email": "not-an-email", "password": PASSWORD})
    assert response.status_code == 422


def test_register_rejects_short_password(client: TestClient) -> None:
    response = client.post(REGISTER_URL, json={"email": EMAIL, "password": "short"})
    assert response.status_code == 422


def test_register_rejects_overlong_password(client: TestClient) -> None:
    response = client.post(
        REGISTER_URL, json={"email": EMAIL, "password": "x" * 73}
    )
    assert response.status_code == 422


# --- Login ------------------------------------------------------------------


def test_login_returns_bearer_token_and_host(client: TestClient) -> None:
    _register(client)
    body = _login(client)
    assert body["token_type"] == "bearer"
    assert body["token"]
    assert body["host"]["email"] == EMAIL


def test_login_is_case_insensitive_for_email(client: TestClient) -> None:
    _register(client)
    body = _login(client, email="HOST@EXAMPLE.COM")
    assert body["host"]["email"] == EMAIL


def test_login_wrong_password_rejected(client: TestClient) -> None:
    _register(client)
    response = client.post(LOGIN_URL, json={"email": EMAIL, "password": "wrong-password"})
    assert response.status_code == 401
    assert "invalid email or password" in response.json()["detail"]


def test_login_unknown_email_rejected(client: TestClient) -> None:
    response = client.post(LOGIN_URL, json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 401


# --- Protected host endpoint (/me) -----------------------------------------


def test_me_requires_authentication(client: TestClient) -> None:
    response = client.get(ME_URL)
    assert response.status_code == 401


def test_me_rejects_invalid_token(client: TestClient) -> None:
    response = client.get(ME_URL, headers=_auth_headers("not-a-real-token"))
    assert response.status_code == 401
    assert "invalid or expired token" in response.json()["detail"]


def test_me_returns_current_host(client: TestClient) -> None:
    _register(client)
    token = _login(client)["token"]
    response = client.get(ME_URL, headers=_auth_headers(token))
    assert response.status_code == 200
    assert response.json()["email"] == EMAIL


def test_me_returns_own_host_not_another(client: TestClient) -> None:
    """Each token authenticates exactly the host it was issued to (the
    foundation for the M4 'hosts cannot modify each other's sessions' rule)."""
    _register(client, email=EMAIL)
    _register(client, email=OTHER_EMAIL)
    token_a = _login(client, email=EMAIL)["token"]
    token_b = _login(client, email=OTHER_EMAIL)["token"]

    response_a = client.get(ME_URL, headers=_auth_headers(token_a))
    response_b = client.get(ME_URL, headers=_auth_headers(token_b))
    assert response_a.status_code == 200
    assert response_b.status_code == 200
    assert response_a.json()["email"] == EMAIL
    assert response_b.json()["email"] == OTHER_EMAIL
    assert response_a.json()["id"] != response_b.json()["id"]


# --- Logout ----------------------------------------------------------------


def test_logout_revokes_token(client: TestClient) -> None:
    _register(client)
    token = _login(client)["token"]

    logout_response = client.post(LOGOUT_URL, headers=_auth_headers(token))
    assert logout_response.status_code == 204

    me_response = client.get(ME_URL, headers=_auth_headers(token))
    assert me_response.status_code == 401


def test_logout_requires_authentication(client: TestClient) -> None:
    response = client.post(LOGOUT_URL)
    assert response.status_code == 401


# --- Token/credential hygiene at rest --------------------------------------


async def test_password_is_stored_hashed(client: TestClient, session: AsyncSession) -> None:
    _register(client)
    host = await session.scalar(select(Host).where(Host.email == EMAIL))
    assert host is not None
    assert host.password_hash != PASSWORD
    assert host.password_hash.startswith("$2")


async def test_token_is_stored_hashed_not_plaintext(
    client: TestClient, session: AsyncSession
) -> None:
    _register(client)
    raw_token = _login(client)["token"]
    stored = await session.scalar(select(HostAuthToken))
    assert stored is not None
    assert stored.token_hash != raw_token
    assert stored.token_hash == hash_auth_token(raw_token)


async def test_expired_token_is_rejected(client: TestClient, session: AsyncSession) -> None:
    _register(client)
    raw_token = _login(client)["token"]

    stored = await session.scalar(select(HostAuthToken))
    assert stored is not None
    stored.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await session.commit()

    response = client.get(ME_URL, headers=_auth_headers(raw_token))
    assert response.status_code == 401
