"""Tests for the M17 security/abuse protections and the security helpers.

Security helpers (password hashing, auth tokens) are covered first (M3); the
M17 additions cover the in-process rate limiter (unit, with an injectable clock)
and the endpoint wiring (a join storm returns 429 once the per-IP limit is
exceeded).
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.ratelimit import RateLimitExceededError, RateLimiter
from app.core.security import (
    generate_auth_token,
    hash_auth_token,
    hash_password,
    verify_password,
)

SESSIONS_URL = "/api/v1/sessions"
JOIN_URL = "/api/v1/join"
REGISTER_URL = "/api/v1/auth/host/register"
LOGIN_URL = "/api/v1/auth/host/login"

EMAIL = "host@example.com"
PASSWORD = "correct-horse-battery-staple"


# --- Security helpers (M3) ----------------------------------------------------------


def test_hash_password_is_not_plaintext() -> None:
    password_hash = hash_password("super-secret")
    assert password_hash != "super-secret"
    assert password_hash.startswith("$2")


def test_verify_password_accepts_correct_password() -> None:
    password_hash = hash_password("super-secret")
    assert verify_password("super-secret", password_hash) is True


def test_verify_password_rejects_wrong_password() -> None:
    password_hash = hash_password("super-secret")
    assert verify_password("wrong-password", password_hash) is False


def test_verify_password_rejects_malformed_hash() -> None:
    assert verify_password("super-secret", "not-a-bcrypt-hash") is False


def test_hash_password_is_unique_per_call() -> None:
    # bcrypt salts every hash, so two hashes of the same password differ.
    assert hash_password("same-password") != hash_password("same-password")


def test_generate_auth_token_is_opaque_and_unique() -> None:
    token_a = generate_auth_token()
    token_b = generate_auth_token()
    assert token_a
    assert token_a != token_b
    # URL-safe base64 tokens contain neither an empty value nor separator chars.
    assert "/" not in token_a and "+" not in token_a


def test_hash_auth_token_is_deterministic_sha256_hex() -> None:
    token = generate_auth_token()
    assert hash_auth_token(token) == hash_auth_token(token)
    assert len(hash_auth_token(token)) == 64
    assert hash_auth_token(token) != token


# --- RateLimiter (unit, M17) --------------------------------------------------------


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_allows_up_to_limit_then_blocks() -> None:
    clock = _FakeClock()
    limiter = RateLimiter(now=clock)
    for _ in range(3):
        limiter.check("key", limit=3, window_seconds=60)
    with pytest.raises(RateLimitExceededError):
        limiter.check("key", limit=3, window_seconds=60)


def test_window_resets_after_elapsed() -> None:
    clock = _FakeClock()
    limiter = RateLimiter(now=clock)
    for _ in range(3):
        limiter.check("key", limit=3, window_seconds=60)
    with pytest.raises(RateLimitExceededError):
        limiter.check("key", limit=3, window_seconds=60)

    clock.now = 61.0  # a fresh window
    limiter.check("key", limit=3, window_seconds=60)  # allowed again
    limiter.check("key", limit=3, window_seconds=60)


def test_keys_are_isolated() -> None:
    clock = _FakeClock()
    limiter = RateLimiter(now=clock)
    for _ in range(3):
        limiter.check("a", limit=3, window_seconds=60)
    with pytest.raises(RateLimitExceededError):
        limiter.check("a", limit=3, window_seconds=60)
    # A different key is unaffected.
    limiter.check("b", limit=3, window_seconds=60)


# --- Endpoint wiring (429, M17) -------------------------------------------------------


def test_join_storm_is_rate_limited(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With limits enabled and a fresh limiter, a join storm hits 429."""
    monkeypatch.setattr("app.api.dependencies.rate_limiter", RateLimiter())
    monkeypatch.setattr(
        "app.api.dependencies.get_settings",
        lambda: Settings(rate_limits_enabled=True),
    )

    register = client.post(
        REGISTER_URL, json={"email": EMAIL, "password": PASSWORD}
    )
    assert register.status_code == 201, register.text
    login = client.post(LOGIN_URL, json={"email": EMAIL, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    session_body = client.post(SESSIONS_URL, json={}, headers=headers).json()

    # The join limit is 10/min per IP: the first ten pass, the 11th is 429.
    for i in range(10):
        response = client.post(
            f"{JOIN_URL}/{session_body['join_code']}/participants",
            json={"nickname": f"User{i}"},
        )
        assert response.status_code == 201, response.text

    response = client.post(
        f"{JOIN_URL}/{session_body['join_code']}/participants",
        json={"nickname": "Spammer"},
    )
    assert response.status_code == 429
    assert "slow down" in response.json()["detail"]


def test_rate_limits_are_disabled_in_tests_by_default(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The suite runs with limits disabled (conftest), so existing tests are
    not coupled to wall-clock windows: more than 10 joins do NOT 429 here."""
    register = client.post(
        REGISTER_URL, json={"email": "other@example.com", "password": PASSWORD}
    )
    assert register.status_code == 201, register.text
    login = client.post(
        LOGIN_URL, json={"email": "other@example.com", "password": PASSWORD}
    )
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    session_body = client.post(SESSIONS_URL, json={}, headers=headers).json()

    for i in range(12):
        response = client.post(
            f"{JOIN_URL}/{session_body['join_code']}/participants",
            json={"nickname": f"User{i}"},
        )
        assert response.status_code == 201, response.text
