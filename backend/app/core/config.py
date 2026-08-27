"""Application configuration via Pydantic Settings.

All configuration is loaded from environment variables prefixed with
``KARAOKE_`` (and optionally from a ``.env`` file in the working directory).
Defaults target local development with the dockerized PostgreSQL from
``compose.yaml``.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings.

    Field names map to environment variables as ``KARAOKE_<FIELD_NAME>``
    (e.g. ``KARAOKE_DATABASE_URL``). Unknown environment variables are ignored.
    """

    model_config = SettingsConfigDict(
        env_prefix="KARAOKE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Friday Karaoke API"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: str = "postgresql+asyncpg://karaoke:karaoke@localhost:5432/karaoke"
    #: Lifetime of a host bearer token (M3). Logout revokes it early.
    auth_token_ttl_days: int = 30
    #: Public base URL of the frontend, used to build session join URLs (M4).
    #: Defaults to the Vite dev server; set to the deployed frontend in prod.
    public_base_url: str = "http://localhost:5173"
    #: YouTube Data API v3 key for fetching song metadata (M6, decision D33).
    #: Empty means the preview service is not configured (503).
    youtube_api_key: str = ""
    #: Threshold (seconds) above which a video preview carries a long-video
    #: warning (M6, decision D34). Warnings never reject.
    youtube_long_video_seconds: int = 600
    #: Maximum songs a participant may queue total, across all rounds (M10.1,
    #: decision D45). Submissions beyond this are rejected.
    queue_max_songs_per_participant: int = 5
    #: Default post-song cooldown in seconds (M13, PRODUCT_SPEC §10). Applied
    #: after a song ends naturally before the next-singer countdown starts.
    #: Per-session override: ``cooldown_seconds`` on session creation.
    post_song_cooldown_seconds: int = 10
    #: Default next-singer countdown in seconds (M13, PRODUCT_SPEC §10).
    #: Per-session override: ``countdown_seconds`` on session creation.
    next_singer_countdown_seconds: int = 20
    #: How long a participant may go without connecting before their remaining
    #: WAITING songs are cleaned up as absent (M16, PRODUCT_SPEC §6.9/E2).
    absent_participant_cleanup_seconds: int = 1800
    #: Master switch for the in-process rate limits (M17). Tests disable it via
    #: the environment so the suite is not coupled to wall-clock windows.
    rate_limits_enabled: bool = True
    #: In-process TTL (seconds) for the YouTube metadata cache (M17): protects
    #: the Data API daily quota from repeated previews/submissions of the same
    #: video.
    youtube_cache_ttl_seconds: int = 3600
    #: Directory containing the built frontend SPA (index.html + assets). When
    #: set and present, the backend serves it on the same origin (single-image
    #: deployment); None disables SPA serving (dev/tests).
    static_dir: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()
