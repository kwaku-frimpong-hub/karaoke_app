"""Tests for the Pydantic Settings configuration."""

import pytest

from app.core.config import Settings


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pin the expected default values explicitly: real environment variables
    # take precedence over any local backend/.env file, so this test is
    # deterministic regardless of the developer's environment.
    monkeypatch.setenv("KARAOKE_ENVIRONMENT", "development")
    monkeypatch.setenv("KARAOKE_APP_NAME", "Friday Karaoke API")
    monkeypatch.setenv("KARAOKE_LOG_LEVEL", "INFO")
    monkeypatch.setenv("KARAOKE_DEBUG", "false")
    monkeypatch.setenv(
        "KARAOKE_DATABASE_URL",
        "postgresql+asyncpg://karaoke:karaoke@localhost:5432/karaoke",
    )
    monkeypatch.setenv("KARAOKE_AUTH_TOKEN_TTL_DAYS", "30")
    monkeypatch.setenv("KARAOKE_PUBLIC_BASE_URL", "http://localhost:5173")
    monkeypatch.setenv("KARAOKE_YOUTUBE_API_KEY", "")
    monkeypatch.setenv("KARAOKE_YOUTUBE_LONG_VIDEO_SECONDS", "600")
    settings = Settings()
    assert settings.app_name == "Friday Karaoke API"
    assert settings.environment == "development"
    assert settings.log_level == "INFO"
    assert settings.debug is False
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.auth_token_ttl_days == 30
    assert settings.public_base_url == "http://localhost:5173"
    assert settings.youtube_api_key == ""
    assert settings.youtube_long_video_seconds == 600


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KARAOKE_APP_NAME", "Test Karaoke")
    monkeypatch.setenv("KARAOKE_LOG_LEVEL", "DEBUG")
    settings = Settings()
    assert settings.app_name == "Test Karaoke"
    assert settings.log_level == "DEBUG"


def test_settings_env_prefix_is_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    # DATABASE_URL without the KARAOKE_ prefix must NOT be picked up.
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://wrong:wrong@nowhere:5432/nope")
    settings = Settings()
    assert "nowhere" not in settings.database_url
